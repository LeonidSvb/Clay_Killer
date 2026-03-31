import sys
import re
import json
import os
import uuid
import requests
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

HISTORY_FILE = Path(__file__).parent / "history.json"
SETTINGS_FILE = Path(__file__).parent / "settings.json"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = "openai/gpt-oss-120b"

TIMESTAMP_RULE = (
    "\nВАЖНОЕ ПРАВИЛО: В каждом ответе, где упоминается любая идея, факт, задача, "
    "совет или момент из видео — ОБЯЗАТЕЛЬНО указывай тайминг в формате [MM:SS]. "
    "Без исключений. Даже в списках задач, действиях и выводах — всегда добавляй "
    "[MM:SS] откуда это взято."
)

BASE_SYSTEM_PROMPT = "Ты — личный ассистент для анализа YouTube-видео. Отвечай конкретно, без воды."

DEFAULT_PRESETS = [
    {
        "label": "Главные идеи",
        "prompt": "Выдели 5-7 главных идей из этого видео. Для каждой укажи тайминг [MM:SS].",
    },
    {
        "label": "Что внедрить",
        "prompt": (
            "Что из этого видео я могу внедрить прямо сейчас? Дай конкретный список действий "
            "на ближайшие 48 часов. Убери воду и общие советы. "
            "Для каждого действия укажи тайминг [MM:SS] откуда это взято."
        ),
    },
    {
        "label": "Что шум",
        "prompt": (
            "Что в этом видео — вода, общие слова, или неприменимо ко мне? "
            "Для каждого пункта укажи тайминг [MM:SS]. Можно пропустить без потерь."
        ),
    },
    {
        "label": "Список задач",
        "prompt": (
            "Преврати ключевые идеи видео в список задач с приоритетами. "
            "Для каждой задачи — первый конкретный шаг и тайминг [MM:SS] откуда взята эта идея."
        ),
    },
]


# ── helpers ──────────────────────────────────────────────────────────────────

def extract_video_id(url: str) -> str | None:
    url = url.strip()
    short = re.match(r"(?:https?://)?youtu\.be/([A-Za-z0-9_-]{11})", url)
    if short:
        return short.group(1)
    parsed = urlparse(url)
    if "youtube.com" in parsed.netloc:
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return qs["v"][0]
    if re.match(r"^[A-Za-z0-9_-]{11}$", url):
        return url
    return None


def get_video_meta(video_id: str) -> tuple[str, str]:
    try:
        resp = requests.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        title = (re.search(r'"title":"([^"]+)"', resp.text) or [None, video_id])[1]
        channel = (re.search(r'"ownerChannelName":"([^"]+)"', resp.text) or [None, ""])[1]
        return title, channel
    except Exception:
        return video_id, ""


def get_transcript(video_id: str) -> tuple[str, list[dict], str]:
    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)
    transcript = None
    for lang in ["ru", "en"]:
        try:
            transcript = transcript_list.find_transcript([lang])
            break
        except Exception:
            pass
    if transcript is None:
        codes = [t.language_code for t in transcript_list]
        transcript = transcript_list.find_generated_transcript(codes)
    data = transcript.fetch()

    segments = []
    for entry in data:
        start = int(entry.start)
        segments.append({
            "start": start,
            "timestamp": f"{start // 60:02d}:{start % 60:02d}",
            "text": entry.text.strip(),
        })

    text = "\n".join(f"[{s['timestamp']}] {s['text']}" for s in segments)
    return text, segments, f"{transcript.language} ({transcript.language_code})"


def ts_to_seconds(ts: str) -> int:
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return int(parts[0]) * 60 + int(parts[1])


def render_timestamps(text: str, video_id: str) -> str:
    def replace_ts(m):
        ts = m.group(1) or m.group(2)
        url = f"https://www.youtube.com/watch?v={video_id}&t={ts_to_seconds(ts)}"
        return f"[{ts}]({url})"

    return re.sub(
        r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]|\((\d{1,2}:\d{2}(?::\d{2})?)\)",
        replace_ts,
        text,
    )


# ── settings ─────────────────────────────────────────────────────────────────

def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_settings(s: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def build_system_prompt(user_context: str) -> str:
    parts = [BASE_SYSTEM_PROMPT]
    if user_context.strip():
        parts.append(f"\nИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ:\n{user_context.strip()}")
    parts.append(TIMESTAMP_RULE)
    return "\n".join(parts)


# ── history ───────────────────────────────────────────────────────────────────

def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_history(history: list[dict]) -> None:
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def save_to_history(video_id, title, channel, lang, text, segments):
    history = load_history()
    existing = next((h for h in history if h["video_id"] == video_id), None)
    history = [h for h in history if h["video_id"] != video_id]
    history.insert(0, {
        "video_id": video_id,
        "title": title,
        "channel": channel,
        "language": lang,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "text": text,
        "segments": segments,
        "messages": existing.get("messages", []) if existing else [],
        "tasks": existing.get("tasks", []) if existing else [],
    })
    _save_history(history)


def save_messages(video_id: str, messages: list[dict]) -> None:
    history = load_history()
    for h in history:
        if h["video_id"] == video_id:
            h["messages"] = messages
            break
    _save_history(history)


def save_tasks(video_id: str, tasks: list[dict]) -> None:
    history = load_history()
    for h in history:
        if h["video_id"] == video_id:
            h["tasks"] = tasks
            break
    _save_history(history)


# ── tasks helpers ─────────────────────────────────────────────────────────────

def export_tasks_md(history: list[dict]) -> str:
    lines = ["# Задачи по видео\n"]
    for h in history:
        tasks = h.get("tasks", [])
        if not tasks:
            continue
        yt_url = f"https://www.youtube.com/watch?v={h['video_id']}"
        lines.append(f"## [{h['title']}]({yt_url})\n")
        for t in tasks:
            icon = {"todo": "[ ]", "done": "[x]", "dropped": "[~]"}.get(t["status"], "[ ]")
            ts_part = ""
            if t.get("ts_ref"):
                secs = ts_to_seconds(t["ts_ref"])
                ts_part = f" — [{t['ts_ref']}]({yt_url}&t={secs})"
            lines.append(f"- {icon} {t['text']}{ts_part}")
        lines.append("")
    return "\n".join(lines)


# ── llm ───────────────────────────────────────────────────────────────────────

def chat_with_llm(transcript, messages, user_context="", model=OPENROUTER_MODEL, reasoning="low", temperature=0.7):
    if not OPENROUTER_API_KEY:
        return "Ошибка: OPENROUTER_API_KEY не задан в .env"

    system = build_system_prompt(user_context) + f"\n\nТРАНСКРИПТ ВИДЕО:\n{transcript}"
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, *messages],
        "temperature": temperature,
    }
    if reasoning != "none":
        payload["reasoning"] = {"effort": reasoning}

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ── streamlit ─────────────────────────────────────────────────────────────────

def _in_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


if _in_streamlit():
    import streamlit as st

    st.set_page_config(page_title="YouTube Transcript", layout="wide")

    settings = load_settings()
    history = load_history()

    user_context = settings.get("user_context", "")
    llm_model = settings.get("model", OPENROUTER_MODEL)
    llm_reasoning = settings.get("reasoning", "low")
    llm_temperature = float(settings.get("temperature", 0.7))
    presets = settings.get("presets", DEFAULT_PRESETS)

    st.title("YouTube Transcript")

    tab_video, tab_tasks, tab_settings = st.tabs(["Видео", "Все задачи", "Настройки"])

    # ── TAB: ВИДЕО ────────────────────────────────────────────────────────────
    with tab_video:
        url = st.text_input("Ссылка на видео", placeholder="https://www.youtube.com/watch?v=...")

        if url:
            vid = extract_video_id(url)
            if not vid:
                st.error("Не удалось определить ID видео.")
            else:
                with st.spinner("Получаю транскрипт..."):
                    try:
                        text, segments, lang = get_transcript(vid)
                        title, channel = get_video_meta(vid)
                        save_to_history(vid, title, channel, lang, text, segments)
                        history = load_history()
                        st.success(f"Сохранено: {title}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка: {e}")

        if history:
            f_col, s_col = st.columns([1, 4])
            with f_col:
                only_tasks = st.checkbox("Только с задачами", key="filter_tasks")
            filtered = history if not only_tasks else [
                h for h in history if any(t["status"] == "todo" for t in h.get("tasks", []))
            ]
            options = {
                (f"{h['date']}  —  {h.get('channel', '')}  —  {h['title']}" if h.get("channel")
                 else f"{h['date']}  —  {h['title']}"): h
                for h in filtered
            }
            with s_col:
                selected = st.selectbox("Видео", ["— выбрать —"] + list(options.keys()), label_visibility="collapsed")

            if selected != "— выбрать —":
                h = options[selected]
                video_id = h["video_id"]
                transcript_text = h.get("text", "")
                messages = h.get("messages", [])
                tasks = h.get("tasks", [])

                left, right = st.columns([1, 1])

                # ── левая колонка ─────────────────────────────────────────
                with left:
                    st.image(f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg", width=320)
                    st.caption(f"{h.get('channel', '')}  •  {h['language']}  •  {h['date']}")
                    st.markdown(f"[Открыть на YouTube](https://www.youtube.com/watch?v={video_id})")
                    st.download_button("Скачать TXT", data=transcript_text,
                                       file_name=f"{video_id}.txt", mime="text/plain", key="dl_txt")

                    with st.expander("Транскрипт"):
                        st.code(transcript_text, language=None)

                    st.divider()
                    st.subheader("Задачи")

                    # добавить задачу
                    add_col1, add_col2, add_col3 = st.columns([3, 1, 1])
                    with add_col1:
                        new_text = st.text_input("", placeholder="Новая задача...",
                                                 key="new_task_text", label_visibility="collapsed")
                    with add_col2:
                        new_ts = st.text_input("", placeholder="02:15 (опц.)",
                                               key="new_task_ts", label_visibility="collapsed")
                    with add_col3:
                        if st.button("Добавить", key="btn_add_task", use_container_width=True):
                            if new_text.strip():
                                tasks.append({
                                    "id": str(uuid.uuid4())[:8],
                                    "text": new_text.strip(),
                                    "status": "todo",
                                    "ts_ref": new_ts.strip() or None,
                                    "created": datetime.now().strftime("%Y-%m-%d"),
                                })
                                save_tasks(video_id, tasks)
                                st.rerun()

                    show_dropped = st.checkbox("Показать отброшенные", key="show_dropped")

                    for task in tasks:
                        if task["status"] == "dropped" and not show_dropped:
                            continue

                        cb_col, txt_col, x_col = st.columns([0.4, 5, 0.4])

                        with cb_col:
                            if task["status"] != "dropped":
                                checked = st.checkbox("", value=task["status"] == "done",
                                                      key=f"cb_{task['id']}", label_visibility="collapsed")
                                new_status = "done" if checked else "todo"
                                if new_status != task["status"]:
                                    task["status"] = new_status
                                    save_tasks(video_id, tasks)
                                    st.rerun()

                        with txt_col:
                            label = task["text"]
                            if task["status"] in ("done", "dropped"):
                                label = f"~~{label}~~"
                            if task.get("ts_ref"):
                                secs = ts_to_seconds(task["ts_ref"])
                                yt = f"https://www.youtube.com/watch?v={video_id}&t={secs}"
                                label += f" [{task['ts_ref']}]({yt})"
                            st.markdown(label)

                        with x_col:
                            if task["status"] != "dropped":
                                if st.button("✕", key=f"drop_{task['id']}"):
                                    task["status"] = "dropped"
                                    save_tasks(video_id, tasks)
                                    st.rerun()

                # ── правая колонка (чат) ──────────────────────────────────
                with right:
                    st.subheader("Чат")

                    preset_cols = st.columns(len(presets))
                    chosen_preset = None
                    for i, p in enumerate(presets):
                        with preset_cols[i]:
                            if st.button(p["label"], use_container_width=True, key=f"preset_{i}"):
                                chosen_preset = p["prompt"]

                    st.divider()

                    chat_box = st.container(height=450)
                    with chat_box:
                        for msg in messages:
                            with st.chat_message(msg["role"]):
                                if msg["role"] == "assistant":
                                    st.markdown(render_timestamps(msg["content"], video_id))
                                else:
                                    st.markdown(msg["content"])

                    if messages:
                        if st.button("Очистить чат", key="clear_chat"):
                            save_messages(video_id, [])
                            st.rerun()

                    user_input = st.chat_input("Спроси что-нибудь по видео...")
                    if chosen_preset:
                        user_input = chosen_preset

                    if user_input:
                        messages.append({"role": "user", "content": user_input})
                        with st.spinner("Думаю..."):
                            try:
                                reply = chat_with_llm(transcript_text, messages, user_context,
                                                      llm_model, llm_reasoning, llm_temperature)
                                messages.append({"role": "assistant", "content": reply})
                                save_messages(video_id, messages)
                            except Exception as e:
                                messages.pop()
                                st.error(f"Ошибка LLM: {e}")
                        st.rerun()

    # ── TAB: ВСЕ ЗАДАЧИ ──────────────────────────────────────────────────────
    with tab_tasks:
        all_tasks_exist = any(h.get("tasks") for h in history)

        if not all_tasks_exist:
            st.info("Задач пока нет. Добавь их во вкладке Видео.")
        else:
            status_filter = st.selectbox(
                "Фильтр",
                ["Все", "В планах", "Сделано", "Отброшено"],
                key="all_tasks_filter",
            )
            status_map = {"Все": None, "В планах": "todo", "Сделано": "done", "Отброшено": "dropped"}
            filter_status = status_map[status_filter]

            md_export = export_tasks_md(history)
            st.download_button("Скачать MD", data=md_export,
                               file_name="tasks.md", mime="text/markdown")

            for h in history:
                tasks = h.get("tasks", [])
                visible = [t for t in tasks if filter_status is None or t["status"] == filter_status]
                if not visible:
                    continue

                yt_url = f"https://www.youtube.com/watch?v={h['video_id']}"
                st.markdown(f"### [{h['title']}]({yt_url})")
                st.caption(f"{h.get('channel', '')}  •  {h['date']}")

                for task in visible:
                    icon = {"todo": "⬜", "done": "✅", "dropped": "❌"}.get(task["status"], "⬜")
                    line = f"{icon} {task['text']}"
                    if task.get("ts_ref"):
                        secs = ts_to_seconds(task["ts_ref"])
                        line += f" — [{task['ts_ref']}]({yt_url}&t={secs})"
                    st.markdown(line)

                st.divider()

    # ── TAB: НАСТРОЙКИ ────────────────────────────────────────────────────────
    with tab_settings:
        cfg_col, ctx_col = st.columns([1, 2])

        with cfg_col:
            st.markdown("**LLM**")
            model_input = st.text_input("Модель", value=settings.get("model", OPENROUTER_MODEL))
            reasoning_input = st.selectbox(
                "Reasoning",
                ["low", "medium", "high", "none"],
                index=["low", "medium", "high", "none"].index(settings.get("reasoning", "low")),
                help="none — отключает reasoning (быстрее/дешевле для простых вопросов)",
            )
            temperature_input = st.slider(
                "Temperature", 0.0, 1.5, float(settings.get("temperature", 0.7)), 0.1,
            )

        with ctx_col:
            st.markdown("**Контекст о тебе**")
            user_context_input = st.text_area(
                "ctx", value=settings.get("user_context", ""), height=130,
                placeholder="Кто ты, бизнес, цели, предпочтения — подмешивается в каждый запрос",
                label_visibility="collapsed",
            )

        st.divider()
        st.markdown("**Пресеты**")

        if "presets_draft" not in st.session_state:
            st.session_state.presets_draft = list(settings.get("presets", DEFAULT_PRESETS))

        to_delete = None
        for i, preset in enumerate(st.session_state.presets_draft):
            p1, p2, p3 = st.columns([1, 3, 0.3])
            with p1:
                st.session_state.presets_draft[i]["label"] = st.text_input(
                    "Название", value=preset["label"], key=f"pl_{i}", label_visibility="collapsed"
                )
            with p2:
                st.session_state.presets_draft[i]["prompt"] = st.text_area(
                    "Промпт", value=preset["prompt"], key=f"pp_{i}",
                    height=68, label_visibility="collapsed"
                )
            with p3:
                st.write("")
                st.write("")
                if st.button("✕", key=f"pd_{i}"):
                    to_delete = i

        if to_delete is not None:
            st.session_state.presets_draft.pop(to_delete)
            for key in list(st.session_state.keys()):
                if key.startswith("pl_") or key.startswith("pp_") or key.startswith("pd_"):
                    del st.session_state[key]
            st.rerun()

        if st.button("+ Добавить пресет"):
            st.session_state.presets_draft.append({"label": "Новый", "prompt": ""})
            st.rerun()

        st.write("")
        if st.button("Сохранить настройки", type="primary"):
            settings["user_context"] = user_context_input
            settings["model"] = model_input
            settings["reasoning"] = reasoning_input
            settings["temperature"] = temperature_input
            settings["presets"] = list(st.session_state.presets_draft)
            save_settings(settings)
            st.success("Сохранено")
            st.rerun()


elif __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py app.py <YouTube URL or video ID>")
        sys.exit(1)

    url = sys.argv[1]
    video_id = extract_video_id(url)
    if not video_id:
        print("ERROR: не удалось определить ID видео")
        sys.exit(1)

    print(f"Video ID: {video_id}")
    print("Получаю транскрипт...")
    text, segments, lang = get_transcript(video_id)
    title, channel = get_video_meta(video_id)
    save_to_history(video_id, title, channel, lang, text, segments)

    out_file = Path(__file__).parent / f"{video_id}.txt"
    out_file.write_text(text, encoding="utf-8")
    print(f"Название: {title}")
    print(f"Язык: {lang}")
    print(f"Сохранено в: {out_file}")
    print("-" * 40)
    print(text[:500], "..." if len(text) > 500 else "")

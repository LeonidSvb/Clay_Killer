import sys
import re
import json
import os
import requests
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

HISTORY_FILE = Path(__file__).parent / "history.json"
SETTINGS_FILE = Path(__file__).parent / "settings.json"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = "openai/gpt-oss-120b"

TIMESTAMP_RULE = """
ВАЖНОЕ ПРАВИЛО: В каждом ответе, где упоминается любая идея, факт, задача, совет или момент из видео — ОБЯЗАТЕЛЬНО указывай тайминг в формате [MM:SS]. Без исключений. Даже в списках задач, действиях и выводах — всегда добавляй [MM:SS] откуда это взято.
"""

BASE_SYSTEM_PROMPT = """Ты — личный ассистент для анализа YouTube-видео. Отвечай конкретно, без воды."""

PRESETS = {
    "Главные идеи": "Выдели 5-7 главных идей из этого видео. Для каждой укажи тайминг [MM:SS].",
    "Что внедрить": "Что из этого видео я могу внедрить прямо сейчас? Дай конкретный список действий на ближайшие 48 часов. Убери воду и общие советы. Для каждого действия укажи тайминг [MM:SS] откуда это взято.",
    "Что шум": "Что в этом видео — вода, общие слова, или неприменимо ко мне? Для каждого пункта укажи тайминг [MM:SS]. Можно пропустить без потерь.",
    "Список задач": "Преврати ключевые идеи видео в список задач с приоритетами. Для каждой задачи — первый конкретный шаг и тайминг [MM:SS] откуда взята эта идея.",
}


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
        title_match = re.search(r'"title":"([^"]+)"', resp.text)
        channel_match = re.search(r'"ownerChannelName":"([^"]+)"', resp.text)
        title = title_match.group(1) if title_match else video_id
        channel = channel_match.group(1) if channel_match else ""
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
        minutes = start // 60
        seconds = start % 60
        segments.append({
            "start": start,
            "timestamp": f"{minutes:02d}:{seconds:02d}",
            "text": entry.text.strip(),
        })

    text_with_timestamps = "\n".join(
        f"[{s['timestamp']}] {s['text']}" for s in segments
    )

    return text_with_timestamps, segments, f"{transcript.language} ({transcript.language_code})"


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"user_context": ""}


def save_settings(settings: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def build_system_prompt(user_context: str) -> str:
    parts = [BASE_SYSTEM_PROMPT]
    if user_context.strip():
        parts.append(f"\nИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ:\n{user_context.strip()}")
    parts.append(TIMESTAMP_RULE)
    return "\n".join(parts)


def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_to_history(video_id: str, title: str, channel: str, lang: str, text: str, segments: list[dict]) -> None:
    history = load_history()
    existing = next((h for h in history if h["video_id"] == video_id), None)
    messages = existing.get("messages", []) if existing else []
    history = [h for h in history if h["video_id"] != video_id]
    history.insert(0, {
        "video_id": video_id,
        "title": title,
        "channel": channel,
        "language": lang,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "text": text,
        "segments": segments,
        "messages": messages,
    })
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def save_messages(video_id: str, messages: list[dict]) -> None:
    history = load_history()
    for h in history:
        if h["video_id"] == video_id:
            h["messages"] = messages
            break
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def chat_with_llm(transcript: str, messages: list[dict], user_context: str = "") -> str:
    if not OPENROUTER_API_KEY:
        return "Ошибка: OPENROUTER_API_KEY не задан в .env"

    system_prompt = build_system_prompt(user_context)
    system_with_transcript = system_prompt + f"\n\nТРАНСКРИПТ ВИДЕО:\n{transcript}"

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_with_transcript},
            *messages,
        ],
        "reasoning": {"effort": "low"},
    }

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def render_timestamps(text: str, video_id: str) -> str:
    def ts_to_seconds(ts: str) -> int:
        parts = ts.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return int(parts[0]) * 60 + int(parts[1])

    def replace_ts(m):
        bracket = m.group(1)
        paren = m.group(2)
        ts = bracket or paren
        seconds = ts_to_seconds(ts)
        url = f"https://www.youtube.com/watch?v={video_id}&t={seconds}"
        return f"[{ts}]({url})"

    # ловим [MM:SS], [M:SS], [HH:MM:SS] и те же форматы в скобках (MM:SS)
    pattern = r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]|\((\d{1,2}:\d{2}(?::\d{2})?)\)"
    return re.sub(pattern, replace_ts, text)


def _in_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


if _in_streamlit():
    import streamlit as st

    st.set_page_config(page_title="YouTube Transcript", layout="wide")

    if "dark_mode" not in st.session_state:
        st.session_state.dark_mode = False
    if "chat_input_key" not in st.session_state:
        st.session_state.chat_input_key = 0

    col_title, col_toggle = st.columns([6, 1])
    with col_title:
        st.title("YouTube Transcript")
    with col_toggle:
        st.write("")
        if st.button("🌙" if not st.session_state.dark_mode else "☀️", use_container_width=True):
            st.session_state.dark_mode = not st.session_state.dark_mode
            st.rerun()

    if st.session_state.dark_mode:
        st.markdown("""
        <style>
        html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
            background-color: #0e1117 !important; color: #fafafa !important;
        }
        [data-testid="stSidebar"] { background-color: #161b22 !important; }
        .stTextInput input, .stSelectbox div[data-baseweb="select"] {
            background-color: #161b22 !important; color: #fafafa !important;
        }
        pre, code { background-color: #161b22 !important; color: #fafafa !important; }
        </style>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <style>
        html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
            background-color: #ffffff !important; color: #0e1117 !important;
        }
        pre, code { background-color: #f0f2f6 !important; color: #0e1117 !important; }
        </style>
        """, unsafe_allow_html=True)

    settings = load_settings()
    history = load_history()

    # --- Настройки ---
    with st.expander("Настройки"):
        st.markdown("**Контекст о тебе** — добавляется в каждый запрос к LLM")
        user_context_input = st.text_area(
            "Кто ты, чем занимаешься, цели, предпочтения",
            value=settings.get("user_context", ""),
            height=150,
            placeholder="Например: я фаундер B2B агентства, делаю outreach для SaaS компаний, моя цель — находить применимые стратегии продаж и роста...",
            label_visibility="collapsed",
        )
        if st.button("Сохранить", key="save_settings"):
            settings["user_context"] = user_context_input
            save_settings(settings)
            st.success("Сохранено")

    user_context = settings.get("user_context", "")

    # --- Новый транскрипт ---
    url = st.text_input("Ссылка на видео", placeholder="https://www.youtube.com/watch?v=...")

    if url:
        video_id = extract_video_id(url)
        if not video_id:
            st.error("Не удалось определить ID видео. Проверь ссылку.")
        else:
            with st.spinner("Получаю транскрипт..."):
                try:
                    text, segments, lang = get_transcript(video_id)
                    title, channel = get_video_meta(video_id)
                    save_to_history(video_id, title, channel, lang, text, segments)
                    history = load_history()
                    st.success(f"Сохранено: {title}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка: {e}")

    # --- История + чат ---
    if history:
        options = {
            f"{h['date']}  —  {h.get('channel', '')}  —  {h['title']}" if h.get('channel') else f"{h['date']}  —  {h['title']}": h
            for h in history
        }

        selected_label = st.selectbox("История", ["— выбрать —"] + list(options.keys()))

        if selected_label != "— выбрать —":
            h = options[selected_label]
            video_id = h["video_id"]
            transcript_text = h.get("text", "")
            messages = h.get("messages", [])

            left_col, right_col = st.columns([1, 1])

            with left_col:
                st.image(f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg", width=320)
                st.caption(f"{h.get('channel', '')}  •  {h['language']}  •  {h['date']}")
                st.markdown(f"[Открыть на YouTube](https://www.youtube.com/watch?v={video_id})")
                st.download_button(
                    "Скачать TXT",
                    data=transcript_text,
                    file_name=f"{video_id}.txt",
                    mime="text/plain",
                    key="dl_history",
                )
                with st.expander("Транскрипт"):
                    st.code(transcript_text, language=None)

            with right_col:
                st.subheader("Чат")

                # preset кнопки
                preset_cols = st.columns(len(PRESETS))
                chosen_preset = None
                for i, (label, prompt) in enumerate(PRESETS.items()):
                    with preset_cols[i]:
                        if st.button(label, use_container_width=True, key=f"preset_{i}"):
                            chosen_preset = prompt

                st.divider()

                # история чата
                chat_container = st.container(height=400)
                with chat_container:
                    for msg in messages:
                        with st.chat_message(msg["role"]):
                            if msg["role"] == "assistant":
                                rendered = render_timestamps(msg["content"], video_id)
                                st.markdown(rendered)
                            else:
                                st.markdown(msg["content"])

                # очистить чат
                if messages:
                    if st.button("Очистить чат", key="clear_chat"):
                        save_messages(video_id, [])
                        st.rerun()

                # ввод
                user_input = st.chat_input("Спроси что-нибудь по видео...", key=f"chat_{st.session_state.chat_input_key}")

                if chosen_preset:
                    user_input = chosen_preset

                if user_input:
                    messages.append({"role": "user", "content": user_input})
                    with st.spinner("Думаю..."):
                        try:
                            reply = chat_with_llm(transcript_text, messages, user_context)
                            messages.append({"role": "assistant", "content": reply})
                            save_messages(video_id, messages)
                        except Exception as e:
                            messages.pop()
                            st.error(f"Ошибка LLM: {e}")
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

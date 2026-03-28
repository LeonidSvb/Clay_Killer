import sys
import re
import json
import requests
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter

HISTORY_FILE = Path(__file__).parent / "history.json"


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


def get_transcript(video_id: str) -> tuple[str, str]:
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
    text = TextFormatter().format_transcript(data)
    return text, f"{transcript.language} ({transcript.language_code})"


def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_to_history(video_id: str, title: str, channel: str, lang: str, text: str) -> None:
    history = load_history()
    history = [h for h in history if h["video_id"] != video_id]
    history.insert(0, {
        "video_id": video_id,
        "title": title,
        "channel": channel,
        "language": lang,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "text": text,
    })
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _in_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


if _in_streamlit():
    import streamlit as st

    st.set_page_config(page_title="YouTube Transcript", layout="centered")

    if "dark_mode" not in st.session_state:
        st.session_state.dark_mode = False

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

    history = load_history()

    # --- История ---
    if history:
        options = {
            f"{h['date']}  —  {h.get('channel', '')}  —  {h['title']}" if h.get('channel') else f"{h['date']}  —  {h['title']}": h
            for h in history
        }
        selected_label = st.selectbox("История", ["— выбрать —"] + list(options.keys()))

        if selected_label != "— выбрать —":
            h = options[selected_label]
            st.image(f"https://img.youtube.com/vi/{h['video_id']}/mqdefault.jpg", width=320)
            st.caption(f"{h.get('channel', '')}  •  {h['language']}  •  {h['date']}")
            st.download_button(
                "Скачать TXT",
                data=h["text"],
                file_name=f"{h['video_id']}.txt",
                mime="text/plain",
                key="dl_history",
            )
            with st.expander("Транскрипт", expanded=True):
                st.code(h["text"], language=None)
            st.divider()

    # --- Новый транскрипт ---
    url = st.text_input("Ссылка на видео", placeholder="https://www.youtube.com/watch?v=...")

    if url:
        video_id = extract_video_id(url)
        if not video_id:
            st.error("Не удалось определить ID видео. Проверь ссылку.")
        else:
            with st.spinner("Получаю транскрипт..."):
                try:
                    text, lang = get_transcript(video_id)
                    title, channel = get_video_meta(video_id)
                    save_to_history(video_id, title, channel, lang, text)

                    st.image(f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg", width=320)
                    st.success(f"{title}")
                    st.caption(f"{channel}  •  {lang}" if channel else lang)
                    st.download_button(
                        "Скачать TXT",
                        data=text,
                        file_name=f"{video_id}.txt",
                        mime="text/plain",
                        key="dl_new",
                    )
                    with st.expander("Транскрипт", expanded=True):
                        st.code(text, language=None)

                except Exception as e:
                    st.error(f"Ошибка: {e}")

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
    text, lang = get_transcript(video_id)
    title, channel = get_video_meta(video_id)
    save_to_history(video_id, title, channel, lang, text)

    out_file = Path(__file__).parent / f"{video_id}.txt"
    out_file.write_text(text, encoding="utf-8")
    print(f"Название: {title}")
    print(f"Язык: {lang}")
    print(f"Сохранено в: {out_file}")
    print("-" * 40)
    print(text[:500], "..." if len(text) > 500 else "")

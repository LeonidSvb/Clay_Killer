import streamlit as st
import os
from pathlib import Path
from dotenv import load_dotenv, set_key


ENV_PATH = Path(__file__).parent.parent.parent / ".env"


def _load_env() -> None:
    load_dotenv(ENV_PATH, override=True)
    # Всегда подтягиваем из .env при каждом рендере Settings
    # чтобы изменения в файле подхватывались без перезапуска
    st.session_state.openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    st.session_state.exa_key = os.getenv("EXA_API_KEY", "")
    if not st.session_state.get("working_folder"):
        st.session_state.working_folder = os.getenv("WORKING_FOLDER", "")
    if not st.session_state.get("default_concurrency"):
        st.session_state.default_concurrency = int(os.getenv("DEFAULT_CONCURRENCY", "50"))
    if not st.session_state.get("confidence_threshold"):
        st.session_state.confidence_threshold = int(os.getenv("CONFIDENCE_THRESHOLD", "6"))


def render_settings() -> None:
    _load_env()

    st.subheader("Working Folder")
    st.caption("CSV files in this folder appear automatically in the Table tab.")

    folder_input = st.text_input(
        "Folder path",
        value=st.session_state.working_folder,
        placeholder="C:/Users/you/Desktop/leads/",
        label_visibility="collapsed",
    )
    if folder_input != st.session_state.working_folder:
        if folder_input and not Path(folder_input).exists():
            st.warning(f"Path does not exist: {folder_input}")
        else:
            st.session_state.working_folder = folder_input

    st.divider()
    st.subheader("API Keys")

    show_or = st.checkbox("Show OpenRouter key", value=False, key="show_or")
    or_key = st.text_input(
        "OpenRouter",
        value=st.session_state.openrouter_key,
        type="default" if show_or else "password",
        placeholder="sk-or-v1-...",
    )
    if or_key != st.session_state.openrouter_key:
        st.session_state.openrouter_key = or_key

    show_exa = st.checkbox("Show Exa key", value=False, key="show_exa")
    exa_key = st.text_input(
        "Exa AI",
        value=st.session_state.exa_key,
        type="default" if show_exa else "password",
        placeholder="exa-...",
    )
    if exa_key != st.session_state.exa_key:
        st.session_state.exa_key = exa_key

    if st.button("Save to .env", type="primary"):
        _save_env()
        st.success(".env saved")

    st.divider()
    st.subheader("Defaults")

    c1, c2 = st.columns(2)
    with c1:
        concurrency = st.number_input(
            "Concurrency",
            min_value=1, max_value=200,
            value=st.session_state.default_concurrency,
        )
        if concurrency != st.session_state.default_concurrency:
            st.session_state.default_concurrency = concurrency
    with c2:
        threshold = st.number_input(
            "Confidence threshold",
            min_value=0, max_value=10,
            value=st.session_state.confidence_threshold,
        )
        if threshold != st.session_state.confidence_threshold:
            st.session_state.confidence_threshold = threshold


def _save_env() -> None:
    ENV_PATH.touch(exist_ok=True)
    set_key(str(ENV_PATH), "OPENROUTER_API_KEY", st.session_state.openrouter_key)
    set_key(str(ENV_PATH), "EXA_API_KEY", st.session_state.exa_key)
    set_key(str(ENV_PATH), "WORKING_FOLDER", st.session_state.working_folder)
    set_key(str(ENV_PATH), "DEFAULT_CONCURRENCY", str(st.session_state.default_concurrency))
    set_key(str(ENV_PATH), "CONFIDENCE_THRESHOLD", str(st.session_state.confidence_threshold))
    os.environ["OPENROUTER_API_KEY"] = st.session_state.openrouter_key
    os.environ["EXA_API_KEY"] = st.session_state.exa_key

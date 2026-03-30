import streamlit as st
import os
from pathlib import Path
from dotenv import load_dotenv, set_key


ENV_PATH = Path(__file__).parent.parent.parent / ".env"


def render_settings() -> None:
    load_dotenv(ENV_PATH, override=True)

    st.subheader("Working Folder")
    st.caption("CSV files in this folder appear automatically in the Table tab.")

    folder_val = st.session_state.get("working_folder", "")
    new_folder = st.text_input(
        "Folder path",
        value=folder_val,
        placeholder="C:/Users/you/Desktop/leads/",
        label_visibility="collapsed",
    )
    if new_folder != folder_val:
        if new_folder and not Path(new_folder).exists():
            st.warning(f"Path does not exist: {new_folder}")
        else:
            st.session_state.working_folder = new_folder

    st.divider()
    st.subheader("API Keys")

    show_or = st.toggle("Show OpenRouter key", value=False)
    or_key = st.text_input(
        "OpenRouter API Key",
        value=st.session_state.get("openrouter_key", ""),
        type="default" if show_or else "password",
        placeholder="sk-or-v1-...",
    )
    if or_key != st.session_state.get("openrouter_key"):
        st.session_state.openrouter_key = or_key

    show_exa = st.toggle("Show Exa key", value=False)
    exa_key = st.text_input(
        "Exa AI Key",
        value=st.session_state.get("exa_key", ""),
        type="default" if show_exa else "password",
        placeholder="exa-...",
    )
    if exa_key != st.session_state.get("exa_key"):
        st.session_state.exa_key = exa_key

    if st.button("Save to .env", type="primary"):
        _save_env()
        st.success(".env saved")

    st.divider()
    st.subheader("Enrichment Defaults")
    st.caption("These values are pre-filled in each enrichment config. You can override them per-run.")

    concurrency = st.number_input(
        "Default concurrency (requests in parallel)",
        min_value=1, max_value=200,
        value=st.session_state.get("default_concurrency", 50),
        help="Used as default in LLM, Scraping, and MX enrichments. Each enrichment can override this.",
    )
    if concurrency != st.session_state.get("default_concurrency"):
        st.session_state.default_concurrency = int(concurrency)


def _save_env() -> None:
    ENV_PATH.touch(exist_ok=True)
    set_key(str(ENV_PATH), "OPENROUTER_API_KEY", st.session_state.get("openrouter_key", ""))
    set_key(str(ENV_PATH), "EXA_API_KEY", st.session_state.get("exa_key", ""))
    set_key(str(ENV_PATH), "WORKING_FOLDER", st.session_state.get("working_folder", ""))
    set_key(str(ENV_PATH), "DEFAULT_CONCURRENCY", str(st.session_state.get("default_concurrency", 50)))
    os.environ["OPENROUTER_API_KEY"] = st.session_state.get("openrouter_key", "")
    os.environ["EXA_API_KEY"] = st.session_state.get("exa_key", "")

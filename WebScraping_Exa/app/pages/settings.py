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
    st.caption("Concurrency = number of parallel requests per enrichment type.")

    llm_conc = st.number_input(
        "LLM Extraction — concurrency",
        min_value=1, max_value=200,
        value=st.session_state.get("llm_concurrency", 50),
        key="settings_llm_concurrency",
    )
    if int(llm_conc) != st.session_state.get("llm_concurrency"):
        st.session_state.llm_concurrency = int(llm_conc)

    mx_conc = st.number_input(
        "MX Check — concurrency",
        min_value=1, max_value=200,
        value=st.session_state.get("mx_concurrency", 60),
        key="settings_mx_concurrency",
    )
    if int(mx_conc) != st.session_state.get("mx_concurrency"):
        st.session_state.mx_concurrency = int(mx_conc)


def _save_env() -> None:
    ENV_PATH.touch(exist_ok=True)
    set_key(str(ENV_PATH), "OPENROUTER_API_KEY", st.session_state.get("openrouter_key", ""))
    set_key(str(ENV_PATH), "EXA_API_KEY", st.session_state.get("exa_key", ""))
    set_key(str(ENV_PATH), "WORKING_FOLDER", st.session_state.get("working_folder", ""))
    set_key(str(ENV_PATH), "LLM_CONCURRENCY", str(st.session_state.get("llm_concurrency", 50)))
    set_key(str(ENV_PATH), "MX_CONCURRENCY", str(st.session_state.get("mx_concurrency", 60)))
    os.environ["OPENROUTER_API_KEY"] = st.session_state.get("openrouter_key", "")
    os.environ["EXA_API_KEY"] = st.session_state.get("exa_key", "")

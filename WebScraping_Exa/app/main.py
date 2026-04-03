import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

import streamlit as st
from app.pages.table import render_table
from app.pages.settings import render_settings
from app.pages.database import render as render_database

st.set_page_config(
    page_title="Lead Enrichment",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Инициализация из .env при первом запуске
_DEFAULTS: dict = {
    "df": None,
    "source_file": None,
    "working_folder": os.getenv("WORKING_FOLDER", ""),
    "new_cols": [],
    "selected_input_cols": [],
    "enrichment_type": "LLM Extraction",
    "run_results": None,
    "run_in_progress": False,
    "last_save_map": {},
    "visible_cols": [],
    "filters": [],
    "default_concurrency": int(os.getenv("DEFAULT_CONCURRENCY", "50")),
    "llm_concurrency": int(os.getenv("LLM_CONCURRENCY", "50")),
    "mx_concurrency": int(os.getenv("MX_CONCURRENCY", "60")),
    "panel_enrichment_type": "LLM Extraction",
    "openrouter_key": os.getenv("OPENROUTER_API_KEY", ""),
    "exa_key": os.getenv("EXA_API_KEY", ""),
}

for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

st.markdown(
    "<style>[data-testid='stSidebar']{display:none}[data-testid='collapsedControl']{display:none}</style>",
    unsafe_allow_html=True,
)

tab_table, tab_database, tab_settings = st.tabs(["Table", "Database", "Settings"])

with tab_table:
    render_table()

with tab_database:
    render_database()

with tab_settings:
    render_settings()

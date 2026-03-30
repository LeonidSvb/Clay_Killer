import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

import streamlit as st
from app.pages.table import render_table
from app.pages.settings import render_settings

st.set_page_config(
    page_title="Lead Enrichment",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed",
)

_DEFAULTS: dict = {
    "df": None,
    "source_file": None,
    "working_folder": "",
    "new_cols": [],
    "selected_input_cols": [],
    "panel_open": False,
    "enrichment_type": "LLM Extraction",
    "run_results": None,
    "visible_cols": [],
    "filters": [],
    "default_concurrency": 50,
    "confidence_threshold": 6,
    "openrouter_key": "",
    "exa_key": "",
}

for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

tab_table, tab_settings = st.tabs(["Table", "Settings"])

with tab_table:
    render_table()

with tab_settings:
    render_settings()

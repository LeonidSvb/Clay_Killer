import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime


def render_file_browser() -> None:
    folder = st.session_state.get("working_folder", "")

    col_refresh = st.columns([6, 1])[1]
    with col_refresh:
        if st.button("Refresh", use_container_width=True):
            st.rerun()

    if not folder or not Path(folder).exists():
        st.info("Set working folder in Settings to browse CSV files.")
        _render_upload(folder)
        return

    csv_files = sorted(
        Path(folder).glob("*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not csv_files:
        st.caption(f"No CSV files in {folder}")
        _render_upload(folder)
        return

    for f in csv_files:
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
        is_open = st.session_state.get("source_file") == str(f)

        c1, c2, c3, c4 = st.columns([4, 1, 1, 1])
        with c1:
            if is_open:
                st.markdown(f"**{f.name}**")
            else:
                st.markdown(f.name)
        with c2:
            st.caption(mtime)
        with c3:
            if is_open and st.session_state.df is not None:
                rows = len(st.session_state.df)
                st.caption(f"{rows:,} rows")
            else:
                try:
                    with open(f, encoding="utf-8-sig") as fh:
                        n = sum(1 for _ in fh) - 1
                    st.caption(f"{n:,} rows")
                except Exception:
                    st.caption("?")
        with c4:
            if is_open:
                st.caption("Opened")
            else:
                if st.button("Open", key=f"open_{f.name}", use_container_width=True):
                    _open_file(str(f))

    st.divider()
    _render_upload(folder)


def _open_file(path: str) -> None:
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        df = pd.read_csv(path)
    st.session_state.df = df
    st.session_state.source_file = path
    st.session_state.new_cols = []
    st.session_state.run_results = None
    st.session_state.visible_cols = list(df.columns)  # сброс при открытии нового файла
    st.session_state.filters = []
    st.rerun()


def _render_upload(folder: str = "") -> None:
    uploaded = st.file_uploader("Upload CSV", type="csv", label_visibility="collapsed")
    if uploaded is not None:
        try:
            df = pd.read_csv(uploaded, encoding="utf-8-sig")
        except Exception:
            uploaded.seek(0)
            df = pd.read_csv(uploaded)

        if folder and Path(folder).exists():
            save_path = Path(folder) / uploaded.name
            df.to_csv(save_path, index=False, encoding="utf-8-sig")
            path = str(save_path)
        else:
            path = uploaded.name

        st.session_state.df = df
        st.session_state.source_file = path
        st.session_state.new_cols = []
        st.session_state.run_results = None
        st.session_state.visible_cols = list(df.columns)
        st.session_state.filters = []
        st.rerun()

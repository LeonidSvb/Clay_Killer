import streamlit as st
import pandas as pd
import csv
from pathlib import Path
from datetime import datetime


def _count_rows(path: Path) -> int:
    """Точный подсчёт строк через csv.reader — корректно обрабатывает многострочные ячейки."""
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            return sum(1 for _ in csv.reader(fh)) - 1  # -1 заголовок
    except Exception:
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                return sum(1 for _ in csv.reader(fh)) - 1
        except Exception:
            return -1


def render_file_browser() -> None:
    folder = st.session_state.get("working_folder", "")

    # ── Хедер: открытый файл + кнопки управления ──────────────────────────────
    source = st.session_state.get("source_file")
    opened_name = ""
    if source:
        opened_name = str(source).replace("\\", "/").split("/")[-1]

    c_info, c_refresh, c_upload_btn = st.columns([5, 1, 1])
    with c_info:
        if opened_name:
            n_rows = len(st.session_state.df) if st.session_state.df is not None else "?"
            st.markdown(f"**{opened_name}** — {n_rows:,} rows")
        else:
            st.caption("No file open")
    with c_refresh:
        if st.button("↺ Refresh", use_container_width=True):
            st.rerun()
    with c_upload_btn:
        show_upload = st.toggle("Upload", value=False, label_visibility="collapsed")

    # ── Переключатель источника ────────────────────────────────────────────────
    source_mode = st.radio(
        "Load from",
        ["Folder", "Database"],
        horizontal=True,
        key="fb_source_mode",
        label_visibility="collapsed",
    )

    if source_mode == "Folder":
        _render_folder_section(folder)
    else:
        _render_db_section()

    # ── Upload ─────────────────────────────────────────────────────────────────
    if show_upload:
        _render_upload(folder)


# ---------------------------------------------------------------------------
# Folder source
# ---------------------------------------------------------------------------

def _render_folder_section(folder: str) -> None:
    if folder and Path(folder).exists():
        csv_files = sorted(
            Path(folder).glob("*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if csv_files:
            options = [str(f) for f in csv_files]

            current_source = st.session_state.get("source_file", "")
            try:
                current_idx = options.index(current_source)
            except ValueError:
                current_idx = 0

            c_select, c_open = st.columns([5, 1])
            with c_select:
                selected_idx = st.selectbox(
                    "file_select",
                    range(len(options)),
                    index=current_idx,
                    format_func=lambda i: _label_with_rows(csv_files[i]),
                    label_visibility="collapsed",
                )
            with c_open:
                selected_path = options[selected_idx]
                already_open = selected_path == current_source
                if st.button(
                    "Opened" if already_open else "Open",
                    disabled=already_open,
                    use_container_width=True,
                    key="open_file_btn",
                ):
                    _open_file(selected_path)
        else:
            st.caption(f"No CSV files in {folder}")
    else:
        if folder:
            st.warning(f"Folder not found: {folder}. Set correct path in Settings.")
        else:
            st.info("Set working folder in Settings.")


# ---------------------------------------------------------------------------
# Database source
# ---------------------------------------------------------------------------

def _render_db_section() -> None:
    try:
        from core.db import get_workspaces, get_workspace_leads, is_connected
    except ImportError:
        st.error("core.db not available")
        return

    if not is_connected():
        st.warning("Not connected to database. Check DATABASE_URL in Settings.")
        return

    workspaces = get_workspaces()
    if not workspaces:
        st.info("No workspaces yet. Import a CSV in the Database tab first.")
        return

    def ws_label(ws: dict) -> str:
        rows = ws["total_rows"] or "?"
        date = ws["created_at"].strftime("%m-%d")
        return f"{ws['name']}  ({rows} rows, {date})"

    c_select, c_open = st.columns([5, 1])
    with c_select:
        selected_ws = st.selectbox(
            "db_workspace_select",
            workspaces,
            format_func=ws_label,
            label_visibility="collapsed",
        )
    with c_open:
        current = st.session_state.get("source_file", "")
        already_open = selected_ws is not None and current == f"[DB] {selected_ws['name']}"
        if st.button(
            "Opened" if already_open else "Open",
            disabled=already_open or selected_ws is None,
            use_container_width=True,
            key="open_db_btn",
        ):
            with st.spinner("Loading from database..."):
                leads = get_workspace_leads(selected_ws["id"])
            _open_from_db(selected_ws, leads)


def _open_from_db(workspace: dict, leads: list) -> None:
    if not leads:
        st.warning("No leads in this workspace.")
        return

    rows = []
    for lead in leads:
        row = {k: v for k, v in lead.items() if k not in ("enrichment_data", "wl_id")}
        enrichment = lead.get("enrichment_data") or {}
        if isinstance(enrichment, dict):
            row.update(enrichment)
        rows.append(row)

    df = pd.DataFrame(rows)
    st.session_state.df = df
    st.session_state.source_file = f"[DB] {workspace['name']}"
    st.session_state.new_cols = []
    st.session_state.run_results = None
    st.session_state.visible_cols = list(df.columns)
    st.session_state.filters = []
    st.rerun()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _label_with_rows(f: Path) -> str:
    """Метка для selectbox: имя + кол-во строк."""
    n = _count_rows(f)
    rows_str = f"{n:,} rows" if n >= 0 else "?"
    mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d")
    return f"{f.name}  ({rows_str}, {mtime})"


def _open_file(path: str) -> None:
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        df = pd.read_csv(path)
    st.session_state.df = df
    st.session_state.source_file = path
    st.session_state.new_cols = []
    st.session_state.run_results = None
    st.session_state.visible_cols = list(df.columns)
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

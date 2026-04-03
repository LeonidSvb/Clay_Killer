import streamlit as st
import pandas as pd
import csv
from pathlib import Path
from datetime import datetime

from core import ui_state


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
        ["Folder", "Database", "PlusVibe"],
        horizontal=True,
        key="fb_source_mode",
        label_visibility="collapsed",
    )

    if source_mode == "Folder":
        _render_folder_section(folder)
    elif source_mode == "Database":
        _render_db_section()
    else:
        _render_plusvibe_section()

    # ── Upload ─────────────────────────────────────────────────────────────────
    if show_upload:
        _render_upload(folder)


# ---------------------------------------------------------------------------
# UI state restore helper
# ---------------------------------------------------------------------------

def _restore_ui_state(df: pd.DataFrame, source_file: str, workspace_id) -> None:
    key = ui_state.get_key(source_file, workspace_id)
    saved = ui_state.load_source(key)
    if not saved:
        return

    if "visible_cols" in saved:
        valid = [c for c in saved["visible_cols"] if c in df.columns]
        if valid:
            st.session_state.visible_cols = valid

    if "filters" in saved:
        st.session_state.filters = saved["filters"]

    enr = saved.get("enrichment", {})
    if enr.get("type"):
        st.session_state["panel_enrichment_type"] = enr["type"]
    if enr.get("output_type"):
        st.session_state["panel_output_type"] = enr["output_type"]
    for bool_key in ("include_reasoning", "include_guardrail"):
        if bool_key in enr:
            st.session_state[bool_key] = enr[bool_key]
    if enr.get("email_col"):
        st.session_state["mx_email_col"] = enr["email_col"]
    if enr.get("url_col"):
        st.session_state["exa_url_col"] = enr["url_col"]
    if enr.get("exa_mode"):
        st.session_state["exa_mode"] = enr["exa_mode"]
    if enr.get("prompt_text"):
        st.session_state["prompt_textarea"] = enr["prompt_text"]
        st.session_state["_loaded_prompt_name"] = ""
        st.session_state["_loaded_prompt_text"] = ""


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


def _render_plusvibe_section() -> None:
    try:
        from core.db import get_plusvibe_campaigns, get_plusvibe_lead_statuses, get_plusvibe_leads, is_connected
    except ImportError:
        st.error("core.db not available")
        return

    if not is_connected():
        st.warning("Not connected to database. Check DATABASE_URL in Settings.")
        return

    campaigns = get_plusvibe_campaigns()
    if not campaigns:
        st.info("No campaigns with leads found.")
        return

    all_statuses = sorted({c["status"] for c in campaigns})
    camp_status_filter = st.multiselect(
        "Campaign status",
        options=all_statuses,
        default=["PAUSED"] if "PAUSED" in all_statuses else all_statuses,
        key="pv_camp_status_filter",
        label_visibility="collapsed",
    )
    filtered_campaigns = [c for c in campaigns if c["status"] in camp_status_filter] if camp_status_filter else campaigns

    def camp_label(c: dict) -> str:
        leads = f"{c['lead_count']:,}" if c["lead_count"] else "?"
        rate = f" | reply {c['replied_rate']}%" if c["replied_rate"] else ""
        return f"[{c['status']}] {c['name']}  ({leads} leads{rate})"

    c_select, c_load = st.columns([5, 1])
    with c_select:
        selected = st.selectbox(
            "campaign_select",
            filtered_campaigns,
            format_func=camp_label,
            label_visibility="collapsed",
            key="pv_campaign",
        )

    # Статусы для выбранной кампании
    current_camp_id = selected["id"] if selected else None
    if st.session_state.get("pv_last_campaign_id") != current_camp_id:
        st.session_state["pv_last_campaign_id"] = current_camp_id
        st.session_state.pop("pv_statuses", None)

    if selected:
        avail_statuses = get_plusvibe_lead_statuses(selected["id"])
    else:
        avail_statuses = []

    default_statuses = ["NOT_CONTACTED"] if "NOT_CONTACTED" in avail_statuses else avail_statuses[:1]
    selected_statuses = st.multiselect(
        "Statuses",
        options=avail_statuses,
        default=default_statuses,
        key="pv_statuses",
        label_visibility="collapsed",
    )

    with c_load:
        current = st.session_state.get("source_file", "")
        label = f"[PV] {selected['name']}" if selected else ""
        already_open = current == label
        if st.button(
            "Opened" if already_open else "Load",
            disabled=already_open or not selected or not selected_statuses,
            use_container_width=True,
            key="open_pv_btn",
        ):
            with st.spinner("Loading from PlusVibe DB..."):
                leads = get_plusvibe_leads(selected["id"], selected_statuses)
            _open_from_plusvibe(selected, leads)


def _open_from_plusvibe(campaign: dict, leads: list) -> None:
    if not leads:
        st.warning("No leads found for selected statuses.")
        return

    enrichment_keys: set = set()
    rows = []
    for lead in leads:
        row = {k: v for k, v in lead.items() if k != "enrichment"}
        enrichment = lead.get("enrichment") or {}
        if isinstance(enrichment, dict):
            enrichment_keys.update(enrichment.keys())
            row.update(enrichment)
        rows.append(row)

    df = pd.DataFrame(rows)

    # Скрываем колонки где >80% значений пустые
    non_empty_cols = []
    for col in df.columns:
        filled = df[col].apply(
            lambda v: v is not None and str(v).strip() not in ("", "nan", "None", "null")
        ).sum()
        if filled / max(len(df), 1) > 0.2:
            non_empty_cols.append(col)

    st.session_state.df = df
    st.session_state.source_file = f"[PV] {campaign['name']}"
    st.session_state.workspace_id = None
    st.session_state.new_cols = list(enrichment_keys)
    st.session_state.run_results = None
    st.session_state.visible_cols = non_empty_cols
    st.session_state.filters = []
    _restore_ui_state(df, st.session_state.source_file, None)
    st.rerun()


def _open_from_db(workspace: dict, leads: list) -> None:
    if not leads:
        st.warning("No leads in this workspace.")
        return

    enrichment_keys: set = set()
    rows = []
    for lead in leads:
        row = {k: v for k, v in lead.items() if k not in ("enrichment_data", "wl_id")}
        enrichment = lead.get("enrichment_data") or {}
        if isinstance(enrichment, dict):
            enrichment_keys.update(enrichment.keys())
            row.update(enrichment)
        rows.append(row)

    df = pd.DataFrame(rows)
    st.session_state.df = df
    st.session_state.source_file = f"[DB] {workspace['name']}"
    st.session_state.workspace_id = workspace["id"]
    st.session_state.new_cols = list(enrichment_keys)
    st.session_state.run_results = None
    st.session_state.visible_cols = list(df.columns)
    st.session_state.filters = []
    _restore_ui_state(df, st.session_state.source_file, workspace["id"])
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
    st.session_state.workspace_id = None
    st.session_state.new_cols = []
    st.session_state.run_results = None
    st.session_state.visible_cols = list(df.columns)
    st.session_state.filters = []
    _restore_ui_state(df, path, None)
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
        st.session_state.workspace_id = None
        st.session_state.new_cols = []
        st.session_state.run_results = None
        st.session_state.visible_cols = list(df.columns)
        st.session_state.filters = []
        _restore_ui_state(df, path, None)
        st.rerun()

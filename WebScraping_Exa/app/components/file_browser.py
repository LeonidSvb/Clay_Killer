import streamlit as st
import pandas as pd
import csv
import json
from pathlib import Path
from datetime import datetime

from core import ui_state
from app.components.filter_builder import render_filter_builder

_MASTER_BROWSER_STATE_KEY = "browser:master"
_MASTER_PRESETS_PATH = Path(__file__).resolve().parents[2] / "master_browser_presets.json"
_MASTER_DEFAULT_PREVIEW = [
    "email", "first_name", "last_name", "company_name", "company_website",
    "title", "country", "employees_count", "industry", "website_summary",
]


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


def _fill_pct(series: pd.Series) -> int:
    total = len(series)
    if total == 0:
        return 0
    empty = (series.isna() | series.astype(str).str.strip().isin(["", "nan", "None", "null"])).sum()
    return round((total - int(empty)) / total * 100)


def _load_master_presets() -> dict:
    if not _MASTER_PRESETS_PATH.exists():
        return {}
    try:
        return json.loads(_MASTER_PRESETS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_master_presets(presets: dict) -> None:
    _MASTER_PRESETS_PATH.write_text(
        json.dumps(presets, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
        if st.button("+ Upload", use_container_width=True, key="btn_toggle_upload"):
            st.session_state["_show_upload"] = not st.session_state.get("_show_upload", False)
        show_upload = st.session_state.get("_show_upload", False)

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

    view = st.radio(
        "db_view",
        ["Import batches", "All leads (master)"],
        horizontal=True,
        key="fb_db_view",
        label_visibility="collapsed",
    )

    if view == "All leads (master)":
        _render_master_section()
        return

    workspaces = get_workspaces()
    if not workspaces:
        st.info("No import batches yet. Import a CSV in the Import & Tasks tab first.")
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


def _render_master_section() -> None:
    from core.db import (
        get_master_browser_count,
        get_master_browser_field_options,
        get_master_browser_fields,
        get_master_browser_rows,
    )

    fields = get_master_browser_fields()
    if not fields:
        st.info("Master browser is unavailable until leads_master is reachable.")
        return

    field_map = {field["key"]: field for field in fields}
    _ensure_master_browser_state(fields)

    presets = _load_master_presets()
    c_preset, c_save, c_delete = st.columns([3, 1, 1])
    preset_names = [""] + sorted(presets.keys())
    with c_preset:
        selected_preset = st.selectbox(
            "preset",
            preset_names,
            key="fb_master_preset_select",
            format_func=lambda name: "Load preset" if not name else name,
            label_visibility="collapsed",
        )
        if selected_preset and st.session_state.get("fb_master_last_applied_preset") != selected_preset:
            _apply_master_browser_preset(presets[selected_preset], fields)
    with c_save:
        if st.button("Save preset", use_container_width=True, key="fb_master_save_preset_btn"):
            st.session_state["fb_master_show_preset_name"] = not st.session_state.get("fb_master_show_preset_name", False)
    with c_delete:
        if st.button(
            "Delete preset",
            use_container_width=True,
            disabled=not selected_preset,
            key="fb_master_delete_preset_btn",
        ):
            presets.pop(selected_preset, None)
            _save_master_presets(presets)
            st.session_state["fb_master_preset_select"] = ""
            st.session_state["fb_master_last_applied_preset"] = ""
            st.rerun()

    if st.session_state.get("fb_master_show_preset_name"):
        c_name, c_confirm = st.columns([4, 1])
        with c_name:
            preset_name = st.text_input("Preset name", key="fb_master_preset_name")
        with c_confirm:
            if st.button("Save", use_container_width=True, key="fb_master_preset_confirm_btn") and preset_name.strip():
                presets[preset_name.strip()] = {
                    "filters": st.session_state.get("fb_master_filters", []),
                }
                _save_master_presets(presets)
                st.session_state["fb_master_show_preset_name"] = False
                st.session_state.pop("fb_master_preset_name", None)
                st.session_state["fb_master_preset_select"] = preset_name.strip()
                st.session_state["fb_master_last_applied_preset"] = preset_name.strip()
                st.rerun()

    filters = _render_master_filter_builder(fields, get_master_browser_field_options)
    _save_master_browser_state()

    preview_field_keys = _master_preview_field_keys(fields, filters)

    total = get_master_browser_count([])
    matching = get_master_browser_count(filters)
    preview_rows, selected_meta = get_master_browser_rows(filters=filters, selected_fields=preview_field_keys, limit=10)

    c_info, c_preview, c_open, c_reset = st.columns([4, 1, 1, 1])
    with c_info:
        st.caption(f"matching {matching:,} of {total:,} leads")
    with c_preview:
        preview_clicked = st.button("Preview 10", use_container_width=True, disabled=matching == 0, key="fb_master_preview_btn")
    with c_open:
        if st.button(f"Load {matching:,}", use_container_width=True, disabled=matching == 0, key="open_master_btn"):
            with st.spinner(f"Loading {matching:,} leads from master..."):
                rows, selected_meta = get_master_browser_rows(filters=filters, selected_fields=preview_field_keys, limit=100000)
            _open_from_master(rows, [field["label"] for field in selected_meta])
    with c_reset:
        if st.button("Reset", use_container_width=True, key="fb_master_reset_btn"):
            _reset_master_browser(fields)

    if matching == 0:
        st.caption("No rows match current filters.")
        return

    preview_df = pd.DataFrame(preview_rows)
    if not preview_df.empty:
        rename_map = {col: f"{col} ({_fill_pct(preview_df[col])}%)" for col in preview_df.columns}
        st.dataframe(
            preview_df.rename(columns=rename_map),
            hide_index=True,
            use_container_width=True,
            height=240,
        )


def _ensure_master_browser_state(fields: list[dict]) -> None:
    field_keys = {field["key"] for field in fields}
    if "fb_master_state_loaded" not in st.session_state:
        saved = ui_state.load_named_state(_MASTER_BROWSER_STATE_KEY)
        st.session_state["fb_master_filters"] = [
            filter_row
            for filter_row in saved.get("filters", [])
            if filter_row.get("field") in field_keys
        ]
        st.session_state["fb_master_state_loaded"] = True
        st.session_state.setdefault("fb_master_show_preset_name", False)
        st.session_state.setdefault("fb_master_last_applied_preset", "")
        return

    st.session_state["fb_master_filters"] = [
        filter_row
        for filter_row in st.session_state.get("fb_master_filters", [])
        if filter_row.get("field") in field_keys
    ]


def _save_master_browser_state() -> None:
    ui_state.save_named_state(
        _MASTER_BROWSER_STATE_KEY,
        {
            "filters": st.session_state.get("fb_master_filters", []),
        },
    )


def _apply_master_browser_preset(preset: dict, fields: list[dict]) -> None:
    field_keys = {field["key"] for field in fields}
    st.session_state["fb_master_filters"] = [
        filter_row
        for filter_row in preset.get("filters", [])
        if filter_row.get("field") in field_keys
    ]
    st.session_state["fb_master_last_applied_preset"] = st.session_state.get("fb_master_preset_select", "")
    _save_master_browser_state()
    st.rerun()


def _reset_master_browser(fields: list[dict]) -> None:
    st.session_state["fb_master_filters"] = []
    st.session_state["fb_master_preset_select"] = ""
    st.session_state["fb_master_last_applied_preset"] = ""
    _save_master_browser_state()
    st.rerun()

def _master_preview_field_keys(fields: list[dict], filters: list[dict]) -> list[str]:
    defaults = [field["key"] for field in fields if field["label"] in _MASTER_DEFAULT_PREVIEW] or [
        field["key"] for field in fields[:10]
    ]
    active_filter_fields = [filter_row["field"] for filter_row in filters if filter_row.get("field")]
    ordered = defaults + [field for field in active_filter_fields if field not in defaults]
    return ordered


def _render_master_filter_builder(fields: list[dict], get_field_options) -> list[dict]:
    return render_filter_builder(
        state_key="fb_master_filters",
        fields=fields,
        key_prefix="fb_master",
        get_field_options=get_field_options,
        caption="Master DB filters",
    )


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


def _open_from_master(leads: list, visible_cols: list[str] | None = None) -> None:
    if not leads:
        st.warning("No leads in leads_master.")
        return

    df = pd.DataFrame(leads)
    st.session_state.df = df
    st.session_state.source_file = "[MASTER]"
    st.session_state.workspace_id = None
    st.session_state.new_cols = []
    st.session_state.run_results = None
    st.session_state.visible_cols = visible_cols or list(df.columns)
    st.session_state.filters = []
    st.rerun()


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
        st.session_state["_show_upload"] = False
        _restore_ui_state(df, path, None)
        st.rerun()

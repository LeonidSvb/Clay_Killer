"""
app/components/plusvibe_push.py — Push enriched lead data back to PlusVibe.

Only renders when source_file starts with "[PV]".

Columns: all visible_cols except operational (status, label, mx, counts, email).
Default: non-source cols checked, source cols unchecked.
Execution: queues a task to DB → worker picks it up (non-blocking).
"""

import os
import queue
import threading
import time

import pandas as pd
import streamlit as st

from app.utils.plusvibe_api import PLUSVIBE_SOURCE_COLS, push_leads_batch

# Columns that never make sense to push to PlusVibe
_SKIP_COLS = {
    "email", "status", "label", "mx", "sent_step", "total_steps",
    "replied_count", "opened_count",
}


def render_plusvibe_push(filtered_df: pd.DataFrame) -> None:
    source = st.session_state.get("source_file", "")
    if not source.startswith("[PV]"):
        return

    api_key = os.getenv("PLUSVIBE_API_KEY", "").strip()
    workspace_id = os.getenv("PLUSVIBE_WORKSPACE_ID", "").strip()
    base_url = os.getenv("PLUSVIBE_BASE_URL", "https://api.plusvibe.ai/api/v1").strip()

    if not api_key or not workspace_id:
        st.warning("PLUSVIBE_API_KEY or PLUSVIBE_WORKSPACE_ID not set in .env")
        return

    df = st.session_state.get("df")
    if df is None or "email" not in df.columns:
        return

    with st.expander("Push to PlusVibe", expanded=False):
        _render_push_ui(filtered_df, df, api_key, workspace_id, base_url)


def _render_push_ui(
    filtered_df: pd.DataFrame,
    df: pd.DataFrame,
    api_key: str,
    workspace_id: str,
    base_url: str,
) -> None:
    # Show push result if available
    push_results = st.session_state.get("_pv_push_results")
    if push_results is not None:
        _render_push_results(push_results)
        if st.button("Push again", key="_pv_btn_again"):
            st.session_state.pop("_pv_push_results", None)
            st.rerun()
        return

    # Columns available to push = visible_cols minus skip list
    visible = st.session_state.get("visible_cols", list(df.columns))
    pushable_cols = [c for c in visible if c in df.columns and c not in _SKIP_COLS]

    if not pushable_cols:
        st.info("No columns to push.")
        return

    col_map: dict[str, str] = {}

    for col in pushable_cols:
        is_new = col not in PLUSVIBE_SOURCE_COLS
        c1, c2, c3 = st.columns([1, 2, 3])
        with c1:
            checked = st.checkbox(
                col,
                value=is_new,
                key=f"_pv_check_{col}",
            )
        with c2:
            if checked:
                default_key = col.lower().replace(" ", "_").lstrip("_")
                var_key = st.text_input(
                    "var",
                    value=default_key,
                    key=f"_pv_varkey_{col}",
                    label_visibility="collapsed",
                    help="Name used in PlusVibe template as {{name}}. No leading underscores.",
                )
                if var_key.startswith("_"):
                    with c3:
                        st.caption("Cannot start with _")
                elif var_key.strip():
                    col_map[col] = var_key.strip()

    if not col_map:
        st.caption("Select at least one column.")
        return

    valid_rows = filtered_df[
        filtered_df["email"].notna() &
        (filtered_df["email"].astype(str).str.strip() != "")
    ]
    n = len(valid_rows)
    est_min = n * 0.21 / 60 / 5  # 5 workers

    st.divider()
    c1, c2 = st.columns([3, 1])
    with c1:
        st.caption(f"{n:,} leads · {len(col_map)} column(s) · ~{est_min:.1f} min")
    with c2:
        if st.button(
            f"Push {n:,} leads",
            type="primary",
            use_container_width=True,
            key="_pv_btn_push",
            disabled=n == 0,
        ):
            rows = valid_rows[[c for c in ["email"] + list(col_map.keys()) if c in valid_rows.columns]].to_dict(orient="records")
            _queue_or_run(rows, col_map, api_key, workspace_id, base_url)


def _queue_or_run(
    rows: list,
    col_map: dict,
    api_key: str,
    workspace_id: str,
    base_url: str,
) -> None:
    """Try to queue as a DB task (non-blocking). Fall back to inline thread."""
    try:
        from core.tasks import create_task
        payload = {
            "enrichment_type": "plusvibe_push",
            "col_map": col_map,
            "rows": rows,
            "api_key": api_key,
            "workspace_id": workspace_id,
            "base_url": base_url,
        }
        task_id = create_task(workspace_id=None, payload=payload, total=len(rows))
        if task_id:
            st.success(f"Task #{task_id} queued — {len(rows):,} leads. Worker is pushing in background.")
            return
    except Exception:
        pass

    # Fallback: inline thread
    _start_inline(rows, col_map, api_key, workspace_id, base_url)


def _start_inline(rows, col_map, api_key, workspace_id, base_url):
    pq: queue.Queue = queue.Queue()
    se = threading.Event()
    holder: list = []

    def worker():
        holder.extend(push_leads_batch(rows, col_map, api_key, workspace_id, pq, se, base_url))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    st.session_state["_pv_push_running"] = True
    st.session_state["_pv_push_thread"] = thread
    st.session_state["_pv_push_queue"] = pq
    st.session_state["_pv_push_stop"] = se
    st.session_state["_pv_push_holder"] = holder
    st.session_state["_pv_push_t0"] = time.time()
    st.rerun()

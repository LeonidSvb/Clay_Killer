"""
app/components/enrichment_panel.py — Enrichment side panel.

Supports:
  - LLM Extraction: prompt editor, output type, OpenRouter
  - MX Check: email column selector, Google DoH DNS lookup

Layout:
  [X Close]
  Type: [ LLM Extraction | MX Check ]
  -- CONFIG (type-specific) --
  -- RUN --
  Rows selector + [Run] button
  Progress bar
  -- OUTPUT --
  Preview table + column save UI
  Run summary stats
"""

import os
import queue
import threading
import time
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

from app.components.prompt_editor import render_prompt_editor
from app.enrichments.exa import run_exa_enrichment, DEFAULT_EXA_QUERY
from app.enrichments.llm import run_llm_enrichment
from app.enrichments.mx import run_mx_enrichment
from app.utils.logger import get_logger

_EXA_QUERY_PATH = Path(__file__).parent.parent.parent / "prompts" / "exa_summary_query.txt"

_log = get_logger()


def _save_results_to_db(workspace_id: int, results: list, rename_map: dict) -> None:
    """Save enrichment results to workspace_leads.data in DB."""
    try:
        from core.db import save_enrichment_batch
        df_full = st.session_state.get("df")
        if df_full is None or "email" not in df_full.columns:
            return
        rows_to_save = []
        for r in results:
            if not r.get("ok") or not r.get("data"):
                continue
            idx = r["idx"]
            try:
                email = str(df_full.at[idx, "email"]).strip()
            except Exception:
                continue
            if not email or "@" not in email:
                continue
            data = {rename_map.get(k, k): v for k, v in r["data"].items() if rename_map.get(k)}
            if data:
                rows_to_save.append({"email": email, "data": data})
        if rows_to_save:
            save_enrichment_batch(workspace_id, rows_to_save)
            _log.info(f"Saved {len(rows_to_save)} enrichment rows to DB workspace {workspace_id}")
    except Exception as e:
        _log.error(f"DB save failed: {e}")


# ── Run summary ────────────────────────────────────────────────────────────────

def _render_run_summary(results: list[dict], elapsed: float) -> None:
    ok = sum(1 for r in results if r["ok"])
    errors = len(results) - ok
    st.caption(
        f"Completed in {elapsed:.1f}s | "
        f"{len(results)} processed | ok: {ok} | errors: {errors}"
    )

    all_keys: set[str] = set()
    for r in results:
        if r["ok"] and r.get("data"):
            all_keys.update(r["data"].keys())
    all_keys.discard("raw")
    all_keys.discard("confidence")

    if not all_keys:
        return

    for key in sorted(all_keys):
        values = [r["data"][key] for r in results if r["ok"] and key in r.get("data", {})]
        if not values:
            continue

        str_values = [str(v) for v in values]
        unique = set(str_values)

        if len(unique) <= 8:
            counts = Counter(str_values)
            total = len(str_values)
            lines = [f"**{key}**"]
            for val, cnt in counts.most_common():
                pct = cnt / total * 100
                lines.append(f"- {val}: {cnt} ({pct:.0f}%)")
            st.markdown("\n".join(lines))

        elif all(isinstance(v, (int, float)) for v in values):
            nums = [float(v) for v in values]
            st.markdown(
                f"**{key}**: avg {sum(nums)/len(nums):.1f} / "
                f"min {min(nums)} / max {max(nums)}"
            )

        else:
            st.markdown(f"**{key}**: {len(unique)} unique values")


# ── Output section (after run) ─────────────────────────────────────────────────

def _render_output_section(df: pd.DataFrame) -> None:
    results: list[dict] = st.session_state.get("run_results", [])
    elapsed: float = st.session_state.get("run_elapsed", 0.0)

    if not results:
        return

    st.markdown("**Output**")

    # Preview table — source cols + output cols, scrollable
    ok_results = [r for r in results if r["ok"] and r.get("data")]
    if ok_results:
        prompt_cols = st.session_state.get("run_prompt_cols", [])
        df_full: pd.DataFrame | None = st.session_state.get("df")

        preview_rows = []
        for r in ok_results:
            row_data = {}
            # Source columns used in prompt
            if df_full is not None and prompt_cols:
                for pc in prompt_cols:
                    if pc in df_full.columns:
                        val = df_full.at[r["idx"], pc]
                        row_data[pc] = str(val)[:60] if str(val) not in ("nan", "None") else ""
            row_data.update({k: v for k, v in r["data"].items() if k != "raw"})
            preview_rows.append(row_data)

        preview_df = pd.DataFrame(preview_rows)

        # Column config: small width for short-value cols, center via Styler
        _SMALL_COLS = {"confidence", "score", "result", "mx_provider"}
        col_cfg = {}
        center_cols = []
        for col in preview_df.columns:
            if col in _SMALL_COLS or col == "row":
                col_cfg[col] = st.column_config.Column(col, width="small")
                center_cols.append(col)

        styled = preview_df.style
        if center_cols:
            styled = styled.set_properties(
                subset=[c for c in center_cols if c in preview_df.columns],
                **{"text-align": "center"},
            )

        st.dataframe(
            styled,
            hide_index=True,
            use_container_width=True,
            height=min(400, 36 + len(preview_df) * 35),
            column_config=col_cfg if col_cfg else None,
        )

    # Run summary stats
    _render_run_summary(results, elapsed)

    st.markdown("---")

    # Collect all output keys from successful results
    all_keys: set[str] = set()
    for r in results:
        if r["ok"] and r.get("data"):
            all_keys.update(r["data"].keys())
    all_keys.discard("raw")

    if not all_keys:
        st.warning("No data keys found in results.")
        return

    st.markdown("**Choose columns to add:**")

    # Determine defaults for checkboxes + rename fields:
    # Priority 1: last_save_map from previous Save in this session
    # Priority 2: fill_missing_col — if opened via "fill N empty" button,
    #             auto-check only the key matching that column name
    last_save_map: dict[str, str] = st.session_state.get("last_save_map", {})
    fill_target: str | None = st.session_state.get("fill_missing_col") \
        if st.session_state.get("row_mode") == "Fill missing" else None

    def _default_include(key: str) -> bool:
        if last_save_map:
            return key in last_save_map
        if fill_target is not None:
            return key == fill_target
        return True

    def _default_rename(key: str) -> str:
        if last_save_map and key in last_save_map:
            return last_save_map[key]
        prompt_default = st.session_state.get("prompt_default_output_col", "")
        if prompt_default and key == "value":
            return prompt_default
        return key

    # Column include + rename UI
    col_selections: dict[str, str | None] = {}
    for key in sorted(all_keys):
        c1, c2 = st.columns([1, 2])
        with c1:
            include = st.checkbox(key, value=_default_include(key), key=f"col_include_{key}")
        with c2:
            if include:
                new_name = st.text_input(
                    "name", value=_default_rename(key),
                    key=f"col_rename_{key}",
                    label_visibility="collapsed",
                )
                col_selections[key] = new_name
            else:
                col_selections[key] = None

    # Rerun / Save / Discard
    r_col, s1, s2 = st.columns(3)
    with r_col:
        if st.button("Rerun", use_container_width=True, key="_btn_rerun"):
            st.session_state["panel_rerun"] = True
            st.session_state["run_results"] = None
            st.session_state["run_elapsed"] = 0.0
            st.rerun()
    with s1:
        if st.button("Save to table", type="primary", use_container_width=True):
            rename_map = {k: v for k, v in col_selections.items() if v is not None}
            new_col_names = list(rename_map.values())

            for result in results:
                if not result["ok"] or not result.get("data"):
                    continue
                idx = result["idx"]
                for src_key, dst_name in rename_map.items():
                    if src_key in result["data"]:
                        st.session_state.df.at[idx, dst_name] = result["data"][src_key]

            existing_new = st.session_state.get("new_cols", [])
            st.session_state.new_cols = list(set(existing_new + new_col_names))
            st.session_state.last_save_map = rename_map
            st.session_state.run_results = None
            st.session_state.run_elapsed = 0.0
            st.session_state.visible_cols = []

            workspace_id = st.session_state.get("workspace_id")
            if workspace_id:
                # DB mode: save enrichment results to workspace_leads.data
                _save_results_to_db(workspace_id, results, rename_map)
            else:
                # CSV mode: auto-save back to file
                source = st.session_state.get("source_file")
                if source:
                    try:
                        st.session_state.df.to_csv(source, index=False)
                    except Exception as e:
                        st.warning(f"Auto-save failed: {e}")
            st.rerun()

    with s2:
        if st.button("Discard", use_container_width=True):
            st.session_state.run_results = None
            st.session_state.run_elapsed = 0.0
            st.rerun()


# ── Run section ────────────────────────────────────────────────────────────────

def _is_empty(val) -> bool:
    import pandas as _pd
    if _pd.isna(val):
        return True
    return str(val).strip() in ("", "nan", "None")


def _get_row_indices(
    df: pd.DataFrame,
    filtered_df: pd.DataFrame,
    fill_col: str | None = None,
) -> list[int]:
    """Render row mode radio and return selected row indices."""
    prefill_col = st.session_state.pop("panel_prefill_fill_col", None)
    default_mode_idx = 0
    row_modes = ["Preview 10", "All", "Filtered", "Custom", "Fill missing"]
    if prefill_col:
        default_mode_idx = row_modes.index("Fill missing")
        st.session_state["fill_missing_col"] = prefill_col

    row_mode = st.radio(
        "Rows",
        row_modes,
        index=default_mode_idx,
        horizontal=True,
        key="row_mode",
        label_visibility="collapsed",
    )

    if row_mode == "Preview 10":
        row_indices = list(range(min(10, len(df))))
    elif row_mode == "All":
        row_indices = list(range(len(df)))
    elif row_mode == "Filtered":
        row_indices = list(filtered_df.index)
    elif row_mode == "Custom":
        custom_n = st.number_input("Rows to run", min_value=1, max_value=len(df),
                                   value=min(50, len(df)), key="custom_row_count")
        row_indices = list(range(int(custom_n)))
    else:  # Fill missing
        all_cols = list(filtered_df.columns)
        saved_col = st.session_state.get("fill_missing_col")
        default_col = saved_col if saved_col in all_cols else (fill_col if fill_col in all_cols else all_cols[0])
        target_col = st.selectbox(
            "Fill empty rows in column:",
            options=all_cols,
            index=all_cols.index(default_col),
            key="fill_missing_col",
        )
        empty_mask = filtered_df[target_col].apply(_is_empty)
        row_indices = list(filtered_df[empty_mask].index)

    st.caption(f"{len(row_indices):,} rows selected")
    return row_indices


def _render_run_section_llm(
    df: pd.DataFrame,
    filtered_df: pd.DataFrame,
    prompt_text: str | None,
    include_reasoning: bool = False,
    include_guardrail: bool = False,
) -> None:
    st.markdown("**Run**")
    autorun = st.session_state.pop("panel_autorun", False)
    row_indices = _get_row_indices(df, filtered_df)
    running = st.session_state.get("run_in_progress", False)
    output_type = st.session_state.get("panel_output_type", "Extract")
    workspace_id = st.session_state.get("workspace_id")

    if autorun and not running:
        _do_run_llm(df, row_indices, prompt_text, output_type, include_reasoning, include_guardrail)
        return

    if workspace_id:
        c1, c2 = st.columns(2)
        with c1:
            if st.button(
                "Running..." if running else "Run (inline)",
                use_container_width=True, key="btn_run", disabled=running,
            ):
                _do_run_llm(df, row_indices, prompt_text, output_type, include_reasoning, include_guardrail)
        with c2:
            output_col = st.session_state.get("last_save_map", {})
            output_col_name = list(output_col.values())[0] if output_col else "result"
            if st.button("Queue (background)", type="primary", use_container_width=True, key="btn_queue_llm", disabled=running):
                _queue_llm_task(workspace_id, df, row_indices, prompt_text, output_type,
                                include_reasoning, include_guardrail, output_col_name)
    else:
        if st.button(
            "Running..." if running else "Run",
            type="primary", use_container_width=True, key="btn_run", disabled=running,
        ):
            _do_run_llm(df, row_indices, prompt_text, output_type, include_reasoning, include_guardrail)


def _render_run_section_mx(df: pd.DataFrame, filtered_df: pd.DataFrame, email_col: str) -> None:
    st.markdown("**Run**")
    autorun = st.session_state.pop("panel_autorun", False)
    row_indices = _get_row_indices(df, filtered_df)
    running = st.session_state.get("run_in_progress", False)
    workspace_id = st.session_state.get("workspace_id")

    if autorun and not running:
        _do_run_mx(df, row_indices, email_col)
        return

    if workspace_id:
        c1, c2 = st.columns(2)
        with c1:
            if st.button(
                "Running..." if running else "Run (inline)",
                use_container_width=True, key="btn_run", disabled=running,
            ):
                _do_run_mx(df, row_indices, email_col)
        with c2:
            if st.button("Queue (background)", type="primary", use_container_width=True, key="btn_queue_mx", disabled=running):
                _queue_mx_task(workspace_id, df, row_indices, email_col)
    else:
        if st.button(
            "Running..." if running else "Run",
            type="primary", use_container_width=True, key="btn_run", disabled=running,
        ):
            _do_run_mx(df, row_indices, email_col)


def _queue_llm_task(
    workspace_id: int,
    df: pd.DataFrame,
    row_indices: list,
    prompt_text: str,
    output_type: str,
    include_reasoning: bool,
    include_guardrail: bool,
    output_col: str,
) -> None:
    try:
        from core.tasks import create_task
        total = len(row_indices)
        payload = {
            "enrichment_type": "llm",
            "prompt_text": prompt_text,
            "output_type": output_type,
            "output_col": output_col,
            "include_reasoning": include_reasoning,
            "include_guardrail": include_guardrail,
            "concurrency": st.session_state.get("llm_concurrency", 50),
            "filter_empty": st.session_state.get("row_mode") == "Fill missing",
        }
        task_id = create_task(workspace_id, payload, total, task_type="llm_extraction")
        if task_id:
            st.success(f"Task #{task_id} queued — {total:,} rows. Worker will process in background.")
            _log.info(f"Queued LLM task {task_id} workspace={workspace_id} rows={total}")
        else:
            st.error("Failed to create task. Check DB connection.")
    except Exception as e:
        st.error(f"Queue failed: {e}")


def _queue_mx_task(
    workspace_id: int,
    df: pd.DataFrame,
    row_indices: list,
    email_col: str,
) -> None:
    try:
        from core.tasks import create_task
        total = len(row_indices)
        payload = {
            "enrichment_type": "mx",
            "email_col": email_col,
            "output_col": "mx_provider",
            "concurrency": st.session_state.get("mx_concurrency", 60),
            "filter_empty": st.session_state.get("row_mode") == "Fill missing",
        }
        task_id = create_task(workspace_id, payload, total, task_type="mx_check")
        if task_id:
            st.success(f"Task #{task_id} queued — {total:,} rows. Worker will process in background.")
            _log.info(f"Queued MX task {task_id} workspace={workspace_id} rows={total}")
        else:
            st.error("Failed to create task. Check DB connection.")
    except Exception as e:
        st.error(f"Queue failed: {e}")


def _start_run_thread(worker_fn) -> None:
    """Start worker thread non-blocking. Stores refs in session_state for polling."""
    pq: queue.Queue = queue.Queue()
    se = threading.Event()
    holder: list[dict] = []

    def worker() -> None:
        holder.extend(worker_fn(pq, se))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    st.session_state["_run_thread"] = thread
    st.session_state["_run_queue"] = pq
    st.session_state["_stop_event"] = se
    st.session_state["_results_holder"] = holder
    st.session_state["_run_t0"] = time.time()
    st.session_state["_run_last_upd"] = {}


def _poll_and_render_progress() -> None:
    """Polls progress queue, renders progress + Stop button. Reruns until done."""
    thread: threading.Thread | None = st.session_state.get("_run_thread")
    pq: queue.Queue | None = st.session_state.get("_run_queue")
    se: threading.Event | None = st.session_state.get("_stop_event")
    holder: list[dict] = st.session_state.get("_results_holder", [])
    t0: float = st.session_state.get("_run_t0", time.time())
    stopped = se.is_set() if se else False

    if st.button("Stop", key="_btn_stop", type="secondary", disabled=stopped):
        if se:
            se.set()
        st.rerun()

    # Drain queue — keep only the latest update
    last_upd: dict = st.session_state.get("_run_last_upd", {})
    if pq:
        try:
            while True:
                last_upd = pq.get_nowait()
        except queue.Empty:
            pass
    st.session_state["_run_last_upd"] = last_upd

    if last_upd:
        total = last_upd["total"] or 1
        pct = last_upd["done"] / total
        st.progress(pct)
        prefix = "Stopping... " if stopped else ""
        st.text(
            f"{prefix}{last_upd['done']}/{last_upd['total']} | "
            f"{last_upd['speed']:.1f}/sec | ETA {last_upd['eta']}s | "
            f"ok={last_upd['ok']} | errors={last_upd['errors']}"
        )
    else:
        st.progress(0)
        st.text("Starting...")

    if thread and not thread.is_alive():
        thread.join()
        elapsed = time.time() - t0
        results = list(holder)

        run_type = st.session_state.get("run_type")
        if run_type == "mx":
            _log_and_store_mx(results, elapsed)
        elif run_type == "exa":
            _log_and_store_exa(results, elapsed)
        else:
            _log_and_store_llm(results, elapsed)

        for k in ["_run_thread", "_run_queue", "_stop_event", "_results_holder", "_run_t0", "_run_last_upd"]:
            st.session_state.pop(k, None)
        st.rerun()
    else:
        time.sleep(0.25)
        st.rerun()


def _log_and_store_llm(results: list[dict], elapsed: float) -> None:
    row_indices = st.session_state.get("run_row_indices", [])
    ok = sum(1 for r in results if r["ok"])
    timings = sorted([r["elapsed"] for r in results if isinstance(r.get("elapsed"), (int, float))])
    if timings:
        p50 = timings[len(timings) // 2]
        p90 = timings[int(len(timings) * 0.9)]
        _log.info(
            f"LLM run done | rows={len(row_indices)} ok={ok} errors={len(results)-ok} "
            f"elapsed={elapsed:.1f}s | p50={p50:.1f}s p90={p90:.1f}s max={timings[-1]:.1f}s"
        )
    else:
        _log.info(f"LLM run done | rows={len(row_indices)} ok={ok} errors={len(results)-ok} elapsed={elapsed:.1f}s")
    for r in results:
        if not r["ok"] and r.get("error"):
            _log.error(f"LLM row {r['idx']} | {r['error']}")
        elif r.get("elapsed", 0) > 15:
            _log.warning(f"LLM slow row {r['idx']} | elapsed={r['elapsed']:.1f}s")
    st.session_state.run_in_progress = False
    st.session_state.run_results = results
    st.session_state.run_elapsed = elapsed


def _log_and_store_mx(results: list[dict], elapsed: float) -> None:
    row_indices = st.session_state.get("run_row_indices", [])
    ok = sum(1 for r in results if r["ok"])
    _log.info(f"MX run done | rows={len(row_indices)} ok={ok} errors={len(results)-ok} elapsed={elapsed:.1f}s")
    for r in results:
        if not r["ok"] and r.get("error"):
            _log.error(f"MX row {r['idx']} | {r['error']}")
    for r in results:
        if r["ok"]:
            r["data"] = {
                "mx_provider": r.get("mx_provider", ""),
                "mx_real": r.get("mx_real", ""),
            }
        else:
            r["data"] = {}
    st.session_state.run_in_progress = False
    st.session_state.run_results = results
    st.session_state.run_elapsed = elapsed


def _log_and_store_exa(results: list[dict], elapsed: float) -> None:
    row_indices = st.session_state.get("run_row_indices", [])
    ok = sum(1 for r in results if r["ok"])
    _log.info(f"Exa run done | rows={len(row_indices)} ok={ok} errors={len(results)-ok} elapsed={elapsed:.1f}s")
    for r in results:
        if not r["ok"] and r.get("error"):
            _log.error(f"Exa row {r['idx']} | {r['error']}")
    st.session_state.run_in_progress = False
    st.session_state.run_results = results
    st.session_state.run_elapsed = elapsed


def _do_run_llm(
    df: pd.DataFrame,
    row_indices: list[int],
    prompt_text: str | None,
    output_type: str = "Extract",
    include_reasoning: bool = False,
    include_guardrail: bool = False,
) -> None:
    if st.session_state.get("run_in_progress"):
        return
    concurrency = st.session_state.get("llm_concurrency", st.session_state.get("default_concurrency", 50))
    api_key = st.session_state.get("openrouter_key", "") or os.getenv("OPENROUTER_API_KEY", "")

    if not api_key:
        st.error("OpenRouter API key not set. Go to Settings tab.")
        return
    if not prompt_text or not prompt_text.strip():
        st.error("Prompt is empty.")
        return

    # Save prompt vars and run params for output preview / rerun
    import re as _re
    st.session_state["run_prompt_cols"] = _re.findall(r"\{\{(.+?)\}\}", prompt_text)
    st.session_state["run_row_indices"] = row_indices
    st.session_state["run_type"] = "llm"

    st.session_state.run_in_progress = True
    _log.info(f"LLM run started | rows={len(row_indices)} output_type={output_type} concurrency={concurrency}")

    def worker_fn(pq, se):
        return run_llm_enrichment(
            df=df, prompt_text=prompt_text, row_indices=row_indices,
            concurrency=concurrency, progress_queue=pq, stop_event=se,
            api_key=api_key, output_type=output_type,
            include_reasoning=include_reasoning, include_guardrail=include_guardrail,
        )

    _start_run_thread(worker_fn)
    st.rerun()


def _do_run_mx(
    df: pd.DataFrame,
    row_indices: list[int],
    email_col: str,
) -> None:
    if st.session_state.get("run_in_progress"):
        return
    concurrency = st.session_state.get("mx_concurrency", st.session_state.get("default_concurrency", 60))

    st.session_state["run_row_indices"] = row_indices
    st.session_state["run_type"] = "mx"
    st.session_state["run_email_col_stored"] = email_col

    st.session_state.run_in_progress = True
    _log.info(f"MX run started | rows={len(row_indices)} email_col={email_col} concurrency={concurrency}")

    def worker_fn(pq, se):
        return run_mx_enrichment(
            df=df, email_col=email_col, row_indices=row_indices,
            concurrency=concurrency, progress_queue=pq, stop_event=se,
        )

    _start_run_thread(worker_fn)
    st.rerun()


def _do_run_exa(
    df: pd.DataFrame,
    row_indices: list[int],
    url_col: str,
    query: str,
) -> None:
    if st.session_state.get("run_in_progress"):
        return
    api_key = st.session_state.get("exa_key", "") or os.getenv("EXA_API_KEY", "")
    if not api_key:
        st.error("Exa API key not set. Go to Settings tab.")
        return
    concurrency = st.session_state.get("exa_concurrency", 50)

    st.session_state["run_row_indices"] = row_indices
    st.session_state["run_type"] = "exa"
    st.session_state["run_exa_url_col"] = url_col
    st.session_state["run_exa_query"] = query

    st.session_state.run_in_progress = True
    _log.info(f"Exa run started | rows={len(row_indices)} url_col={url_col} concurrency={concurrency}")

    def worker_fn(pq, se):
        return run_exa_enrichment(
            df=df, url_col=url_col, row_indices=row_indices,
            query=query, concurrency=concurrency,
            progress_queue=pq, stop_event=se, api_key=api_key,
        )

    _start_run_thread(worker_fn)
    st.rerun()


def _queue_exa_task(
    workspace_id: int,
    df: pd.DataFrame,
    row_indices: list,
    url_col: str,
    query: str,
) -> None:
    try:
        from core.tasks import create_task
        total = len(row_indices)
        payload = {
            "enrichment_type": "exa",
            "url_col": url_col,
            "query": query,
            "output_col": "Website Summary",
            "concurrency": st.session_state.get("exa_concurrency", 50),
            "filter_empty": st.session_state.get("row_mode") == "Fill missing",
        }
        task_id = create_task(workspace_id, payload, total, task_type="exa_scraping")
        if task_id:
            st.success(f"Task #{task_id} queued — {total:,} rows. Worker will process in background.")
            _log.info(f"Queued Exa task {task_id} workspace={workspace_id} rows={total}")
        else:
            st.error("Failed to create task. Check DB connection.")
    except Exception as e:
        st.error(f"Queue failed: {e}")


def _render_run_section_exa(
    df: pd.DataFrame,
    filtered_df: pd.DataFrame,
    url_col: str,
    query: str,
) -> None:
    st.markdown("**Run**")
    autorun = st.session_state.pop("panel_autorun", False)
    row_indices = _get_row_indices(df, filtered_df)
    running = st.session_state.get("run_in_progress", False)
    workspace_id = st.session_state.get("workspace_id")

    if autorun and not running:
        _do_run_exa(df, row_indices, url_col, query)
        return

    if workspace_id:
        c1, c2 = st.columns(2)
        with c1:
            if st.button(
                "Running..." if running else "Run (inline)",
                use_container_width=True, key="btn_run", disabled=running,
            ):
                _do_run_exa(df, row_indices, url_col, query)
        with c2:
            if st.button("Queue (background)", type="primary", use_container_width=True,
                         key="btn_queue_exa", disabled=running):
                _queue_exa_task(workspace_id, df, row_indices, url_col, query)
    else:
        if st.button(
            "Running..." if running else "Run",
            type="primary", use_container_width=True, key="btn_run", disabled=running,
        ):
            _do_run_exa(df, row_indices, url_col, query)


# ── Main panel ─────────────────────────────────────────────────────────────────

def render_enrichment_panel(filtered_df: pd.DataFrame | None = None) -> None:
    df: pd.DataFrame | None = st.session_state.get("df")
    if df is None:
        return

    if filtered_df is None:
        filtered_df = df

    # Handle rerun request (triggered from Rerun button in output section)
    if st.session_state.get("panel_rerun") and not st.session_state.get("run_in_progress"):
        st.session_state.pop("panel_rerun", None)
        _ri = st.session_state.get("run_row_indices", [])
        _rt = st.session_state.get("run_type")
        if _rt == "mx":
            _do_run_mx(df, _ri, st.session_state.get("run_email_col_stored", ""))
        elif _rt == "exa":
            _do_run_exa(
                df, _ri,
                st.session_state.get("run_exa_url_col", ""),
                st.session_state.get("run_exa_query", DEFAULT_EXA_QUERY),
            )
        else:
            _do_run_llm(
                df, _ri,
                st.session_state.get("prompt_textarea", ""),
                st.session_state.get("panel_output_type", "Extract"),
                st.session_state.get("include_reasoning", False),
                st.session_state.get("include_guardrail", False),
            )
        return

    st.markdown("### Enrichment")

    # If run in progress — show progress + Stop, skip the rest of the panel
    if st.session_state.get("run_in_progress"):
        _poll_and_render_progress()
        return

    # Type selector
    enrichment_type = st.selectbox(
        "Type",
        ["LLM Extraction", "MX Check", "Exa Summary"],
        key="panel_enrichment_type",
        label_visibility="collapsed",
    )

    # -- CONFIG (type-specific) --
    if enrichment_type == "LLM Extraction":
        ot_col, r_col, g_col = st.columns([3, 2, 2])
        with ot_col:
            output_type = st.selectbox(
                "Output type",
                ["Boolean", "Score 0-10", "Extract", "Full profile"],
                key="panel_output_type",
                label_visibility="collapsed",
            )
        with r_col:
            include_reasoning = st.checkbox(
                "Include reasoning",
                value=st.session_state.get("include_reasoning", False),
                key="include_reasoning",
                disabled=(output_type != "Extract"),
                help="Add reasoning field to Extract output",
            )
        with g_col:
            include_guardrail = st.checkbox(
                "Flag insufficient data",
                key="include_guardrail",
                help='LLM returns "INSUFFICIENT_DATA" when info is not enough',
            )
        prompt_text = render_prompt_editor(df, output_type)

    elif enrichment_type == "MX Check":
        email_cols = [c for c in df.columns if "email" in c.lower() or "mail" in c.lower()]
        all_cols = list(df.columns)
        default_options = email_cols if email_cols else all_cols
        email_col = st.selectbox(
            "Email column",
            options=default_options,
            key="mx_email_col",
        )
        st.caption("Looks up MX records via DNS and classifies the email provider (Google, Microsoft, Zoho, etc.)")

    else:  # Exa Summary
        url_cols = [c for c in df.columns
                    if any(k in c.lower() for k in ("website", "url", "domain", "site"))]
        all_cols = list(df.columns)
        default_url_options = url_cols if url_cols else all_cols
        url_col = st.selectbox("URL column", options=default_url_options, key="exa_url_col")
        st.caption("Fetches website content summary from Exa AI. Requires Exa API key in Settings.")

        # Exa query editor
        if "exa_query_text" not in st.session_state:
            if _EXA_QUERY_PATH.exists():
                st.session_state.exa_query_text = _EXA_QUERY_PATH.read_text(encoding="utf-8")
            else:
                st.session_state.exa_query_text = DEFAULT_EXA_QUERY

        qcap, qsave = st.columns([5, 1])
        with qcap:
            st.caption("Exa summary query — instructs how to summarize the website")
        with qsave:
            if st.button("Save", key="_btn_save_exa_query", use_container_width=True):
                _EXA_QUERY_PATH.parent.mkdir(parents=True, exist_ok=True)
                _EXA_QUERY_PATH.write_text(st.session_state.exa_query_text, encoding="utf-8")
                st.toast("Exa query saved")

        st.text_area(
            "Exa query",
            height=180,
            key="exa_query_text",
            label_visibility="collapsed",
        )
        exa_query = st.session_state.get("exa_query_text", DEFAULT_EXA_QUERY)

    st.markdown("---")

    # -- OUTPUT (if results exist) --
    if st.session_state.get("run_results") is not None:
        _render_output_section(df)
    else:
        # -- RUN --
        if enrichment_type == "LLM Extraction":
            _render_run_section_llm(df, filtered_df, prompt_text, include_reasoning, include_guardrail)
        elif enrichment_type == "MX Check":
            _render_run_section_mx(df, filtered_df, email_col)
        else:
            _render_run_section_exa(df, filtered_df, url_col, exa_query)

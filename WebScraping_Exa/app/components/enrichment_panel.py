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

import pandas as pd
import streamlit as st

from app.components.prompt_editor import render_prompt_editor
from app.enrichments.llm import run_llm_enrichment
from app.enrichments.mx import run_mx_enrichment


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

    # Preview table — all ok rows, scrollable
    ok_results = [r for r in results if r["ok"] and r.get("data")]
    if ok_results:
        preview_rows = []
        for r in ok_results:
            row_data = {"row": r["idx"]}
            row_data.update({k: v for k, v in r["data"].items() if k != "raw"})
            preview_rows.append(row_data)
        preview_df = pd.DataFrame(preview_rows)
        # Narrow column config for short-value columns (boolean, score, confidence)
        col_cfg = {}
        for col in preview_df.columns:
            if col in ("row", "confidence"):
                col_cfg[col] = st.column_config.NumberColumn(col, width="small")
            elif col in ("result",):
                col_cfg[col] = st.column_config.Column(col, width="small")
            elif col in ("score",):
                col_cfg[col] = st.column_config.NumberColumn(col, width="small")
        st.dataframe(
            preview_df,
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

    # Save / Discard
    s1, s2 = st.columns(2)
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
            st.session_state.last_save_map = rename_map  # remember for next run
            st.session_state.run_results = None
            st.session_state.run_elapsed = 0.0
            # Reset visible_cols so new columns are included in main table
            st.session_state.visible_cols = []
            # Auto-save enriched CSV back to source file
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
        target_col = fill_col or list(df.columns)[0]
        empty_mask = df[target_col].apply(_is_empty)
        row_indices = list(df[empty_mask].index)

    st.caption(f"{len(row_indices):,} rows selected")
    return row_indices


def _render_run_section_llm(df: pd.DataFrame, filtered_df: pd.DataFrame, prompt_text: str | None) -> None:
    st.markdown("**Run**")
    row_indices = _get_row_indices(df, filtered_df)
    if st.button("Run", type="primary", use_container_width=True, key="btn_run"):
        _do_run_llm(df, row_indices, prompt_text, st.session_state.get("panel_output_type", "Extract"))


def _render_run_section_mx(df: pd.DataFrame, filtered_df: pd.DataFrame, email_col: str) -> None:
    st.markdown("**Run**")
    row_indices = _get_row_indices(df, filtered_df)
    if st.button("Run", type="primary", use_container_width=True, key="btn_run"):
        _do_run_mx(df, row_indices, email_col)


def _run_with_progress(worker_fn, row_indices: list[int]) -> tuple[list[dict], float]:
    """Generic threading + progress pattern. Returns (results, elapsed)."""
    progress_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()
    results_holder: list[dict] = []

    def worker() -> None:
        results_holder.extend(worker_fn(progress_queue, stop_event))

    thread = threading.Thread(target=worker, daemon=True)
    progress_bar = st.progress(0)
    status = st.empty()
    t0 = time.time()
    thread.start()

    while thread.is_alive() or not progress_queue.empty():
        try:
            upd = progress_queue.get(timeout=0.4)
            total = upd["total"] or 1
            pct = upd["done"] / total
            progress_bar.progress(pct)
            status.text(
                f"{upd['done']}/{upd['total']} | "
                f"{upd['speed']:.1f}/sec | ETA {upd['eta']}s | "
                f"ok={upd['ok']} | errors={upd['errors']}"
            )
        except queue.Empty:
            pass

    thread.join()
    elapsed = time.time() - t0
    progress_bar.progress(1.0)
    status.text(
        f"{len(results_holder)}/{len(row_indices)} done | "
        f"ok={sum(1 for r in results_holder if r['ok'])} | "
        f"errors={sum(1 for r in results_holder if not r['ok'])}"
    )
    return results_holder, elapsed


def _do_run_llm(
    df: pd.DataFrame,
    row_indices: list[int],
    prompt_text: str | None,
    output_type: str = "Extract",
) -> None:
    concurrency = st.session_state.get("llm_concurrency", st.session_state.get("default_concurrency", 50))
    api_key = st.session_state.get("openrouter_key", "") or os.getenv("OPENROUTER_API_KEY", "")

    if not api_key:
        st.error("OpenRouter API key not set. Go to Settings tab.")
        return
    if not prompt_text or not prompt_text.strip():
        st.error("Prompt is empty.")
        return

    def worker_fn(pq, se):
        return run_llm_enrichment(
            df=df, prompt_text=prompt_text, row_indices=row_indices,
            concurrency=concurrency, progress_queue=pq, stop_event=se,
            api_key=api_key, output_type=output_type,
        )

    results, elapsed = _run_with_progress(worker_fn, row_indices)
    st.session_state.run_results = results
    st.session_state.run_elapsed = elapsed
    st.rerun()


def _do_run_mx(
    df: pd.DataFrame,
    row_indices: list[int],
    email_col: str,
) -> None:
    concurrency = st.session_state.get("mx_concurrency", st.session_state.get("default_concurrency", 60))

    def worker_fn(pq, se):
        return run_mx_enrichment(
            df=df, email_col=email_col, row_indices=row_indices,
            concurrency=concurrency, progress_queue=pq, stop_event=se,
        )

    results, elapsed = _run_with_progress(worker_fn, row_indices)
    # Convert MX results to same format as LLM results for _render_output_section
    for r in results:
        if r["ok"]:
            r["data"] = {
                "mx_provider": r.get("mx_provider", ""),
                "mx_real": r.get("mx_real", ""),
            }
        else:
            r["data"] = {}
    st.session_state.run_results = results
    st.session_state.run_elapsed = elapsed
    st.rerun()


# ── Main panel ─────────────────────────────────────────────────────────────────

def render_enrichment_panel(filtered_df: pd.DataFrame | None = None) -> None:
    df: pd.DataFrame | None = st.session_state.get("df")
    if df is None:
        return

    if filtered_df is None:
        filtered_df = df

    st.markdown("### Enrichment")

    # Type selector
    enrichment_type = st.selectbox(
        "Type",
        ["LLM Extraction", "MX Check"],
        key="panel_enrichment_type",
        label_visibility="collapsed",
    )

    # -- CONFIG (type-specific) --
    if enrichment_type == "LLM Extraction":
        output_type = st.selectbox(
            "Output type",
            ["Boolean", "Score 0-10", "Extract", "Full profile"],
            key="panel_output_type",
            label_visibility="collapsed",
        )
        prompt_text = render_prompt_editor(df, output_type)

    else:  # MX Check
        email_cols = [c for c in df.columns if "email" in c.lower() or "mail" in c.lower()]
        all_cols = list(df.columns)
        default_options = email_cols if email_cols else all_cols
        email_col = st.selectbox(
            "Email column",
            options=default_options,
            key="mx_email_col",
        )
        st.caption("Looks up MX records via DNS and classifies the email provider (Google, Microsoft, Zoho, etc.)")

    st.markdown("---")

    # -- OUTPUT (if results exist) --
    if st.session_state.get("run_results") is not None:
        _render_output_section(df)
    else:
        # -- RUN --
        if enrichment_type == "LLM Extraction":
            _render_run_section_llm(df, filtered_df, prompt_text)
        else:
            _render_run_section_mx(df, filtered_df, email_col)

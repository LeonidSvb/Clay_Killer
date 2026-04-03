import re
import streamlit as st
import pandas as pd
from app.components.file_browser import render_file_browser
from app.components.enrichment_panel import render_enrichment_panel
from app.components.plusvibe_push import render_plusvibe_push
from app.components.col_stats import render_col_stats
from core import ui_state

OPERATORS = ["=", "!=", ">=", "<=", "contains", "not contains", "is empty", "is not empty"]

TABLE_HEIGHT = 320


def _fill_pct(series: pd.Series) -> int:
    total = len(series)
    if total == 0:
        return 0
    empty = series.isna().sum() + (series.astype(str).str.strip().isin(["", "nan", "None"])).sum()
    return round((total - min(int(empty), total)) / total * 100)


def render_table() -> None:
    render_file_browser()

    df: pd.DataFrame | None = st.session_state.get("df")
    if df is None:
        return

    st.divider()
    _render_toolbar(df)
    filtered_df = _apply_filters(df)
    _render_row_count(df, filtered_df)
    _render_col_manager(df)
    visible_cols = _get_visible_cols(filtered_df)
    _render_dataframe(filtered_df, visible_cols)

    source = st.session_state.get("source_file")
    if source:
        ui_state.save_source(
            ui_state.get_key(source, st.session_state.get("workspace_id")),
            {"visible_cols": visible_cols, "filters": st.session_state.get("filters", [])},
        )

    st.divider()
    render_enrichment_panel(filtered_df)
    _render_last_run_stats(df)
    render_plusvibe_push(filtered_df)


def _render_row_count(df: pd.DataFrame, filtered_df: pd.DataFrame) -> None:
    if len(filtered_df) != len(df):
        st.caption(f"{len(filtered_df):,} of {len(df):,} rows (filtered)")
    else:
        st.caption(f"{len(df):,} rows")


def _render_col_manager(df: pd.DataFrame) -> None:
    """Delete buttons for generated columns."""
    new_cols = [c for c in st.session_state.get("new_cols", []) if c in df.columns]
    if not new_cols:
        return

    st.caption("Generated columns:")
    btn_cols = st.columns(min(len(new_cols), 6))
    for i, col in enumerate(new_cols):
        with btn_cols[i % 6]:
            if st.button(f"{col} ✕", key=f"del_col_{col}", use_container_width=True,
                         help=f"Delete column '{col}'"):
                st.session_state.df.drop(columns=[col], inplace=True)
                st.session_state.new_cols = [c for c in st.session_state.new_cols if c != col]
                st.session_state.visible_cols = []
                last_run = st.session_state.get("_last_run_cols", [])
                if col in last_run:
                    st.session_state["_last_run_cols"] = [c for c in last_run if c != col]
                source = st.session_state.get("source_file")
                if source and not source.startswith("[PV]") and not source.startswith("[DB]"):
                    try:
                        st.session_state.df.to_csv(source, index=False)
                    except Exception:
                        pass
                st.rerun()


def _render_last_run_stats(df: pd.DataFrame) -> None:
    """Show stats for columns from the last enrichment run. Dismissable."""
    last_run_cols = [
        c for c in st.session_state.get("_last_run_cols", [])
        if c in df.columns
    ]
    if not last_run_cols:
        return

    st.divider()
    hdr, dismiss_col = st.columns([6, 1])
    with hdr:
        st.markdown(f"**Stats — last run** ({', '.join(last_run_cols)})")
    with dismiss_col:
        if st.button("× Close", key="_btn_close_stats", use_container_width=True):
            st.session_state["_last_run_cols"] = []
            st.rerun()

    for col in last_run_cols:
        if len(last_run_cols) > 1:
            st.markdown(f"**{col}**")
        render_col_stats(df, col)


def _render_toolbar(df: pd.DataFrame) -> None:
    source = st.session_state.get("source_file", "")
    filename = source.replace("\\", "/").split("/")[-1] if source else "untitled"
    n_rows, n_cols = df.shape
    visible = st.session_state.get("visible_cols", [])
    n_visible = len([c for c in visible if c in df.columns]) if visible else n_cols
    cols_label = f"{n_visible} of {n_cols} cols" if n_visible != n_cols else f"{n_cols} cols"

    c1, c2 = st.columns([4, 1])
    with c1:
        st.markdown(f"**{filename}** &nbsp; {n_rows:,} rows &nbsp; {cols_label}")
    with c2:
        _render_filter_toggle(df)


def _render_filter_toggle(df: pd.DataFrame) -> None:
    col_options = list(df.columns)
    filters = st.session_state.get("filters", [])
    active = len([f for f in filters if f.get("val") or f.get("op") in ("is empty", "is not empty")])
    label = f"Filter ({active})" if active else "Filter"

    with st.popover(label, use_container_width=True):
        if st.button("+ Add filter", use_container_width=True):
            st.session_state.filters.append({"col": col_options[0], "op": "=", "val": ""})
            st.rerun()

        to_remove = []
        for i, f in enumerate(st.session_state.filters):
            c1, c2, c3, c4 = st.columns([3, 2, 3, 1])
            with c1:
                new_col = st.selectbox(
                    "col", col_options,
                    index=col_options.index(f["col"]) if f["col"] in col_options else 0,
                    key=f"fc_{i}", label_visibility="collapsed",
                )
                if new_col != f["col"]:
                    f["col"] = new_col
            with c2:
                new_op = st.selectbox(
                    "op", OPERATORS,
                    index=OPERATORS.index(f["op"]) if f["op"] in OPERATORS else 0,
                    key=f"fo_{i}", label_visibility="collapsed",
                )
                if new_op != f["op"]:
                    f["op"] = new_op
            with c3:
                if f["op"] in ("is empty", "is not empty"):
                    st.caption("(no value needed)")
                else:
                    new_val = st.text_input(
                        "val", value=f.get("val", ""),
                        key=f"fv_{i}", label_visibility="collapsed",
                    )
                    if new_val != f.get("val"):
                        f["val"] = new_val
            with c4:
                if st.button("x", key=f"fdel_{i}", use_container_width=True):
                    to_remove.append(i)

        if to_remove:
            for i in reversed(to_remove):
                st.session_state.filters.pop(i)
            st.rerun()

        if st.session_state.filters:
            if st.button("Clear all filters", use_container_width=True):
                st.session_state.filters = []
                st.rerun()


def _apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    filters = st.session_state.get("filters", [])
    result = df.copy()

    for f in filters:
        col = f.get("col")
        op = f.get("op", "=")
        val = f.get("val", "")

        if not col or col not in result.columns:
            continue

        series = result[col]

        try:
            if op == "is empty":
                mask = series.isna() | series.astype(str).str.strip().isin(["", "nan", "None"])
                result = result[mask]
            elif op == "is not empty":
                mask = ~(series.isna() | series.astype(str).str.strip().isin(["", "nan", "None"]))
                result = result[mask]
            elif val == "":
                continue
            elif op == "=":
                try:
                    result = result[pd.to_numeric(series, errors="coerce") == float(val)]
                except ValueError:
                    result = result[series.astype(str).str.lower() == val.lower()]
            elif op == "!=":
                try:
                    result = result[pd.to_numeric(series, errors="coerce") != float(val)]
                except ValueError:
                    result = result[series.astype(str).str.lower() != val.lower()]
            elif op == ">=":
                result = result[pd.to_numeric(series, errors="coerce") >= float(val)]
            elif op == "<=":
                result = result[pd.to_numeric(series, errors="coerce") <= float(val)]
            elif op == "contains":
                result = result[series.astype(str).str.contains(val, case=False, na=False)]
            elif op == "not contains":
                result = result[~series.astype(str).str.contains(val, case=False, na=False)]
        except Exception:
            pass

    return result


def _get_visible_cols(df: pd.DataFrame) -> list[str]:
    saved = st.session_state.get("visible_cols", [])
    available = list(df.columns)
    visible = [c for c in saved if c in available]
    return visible if visible else available


def _render_dataframe(df: pd.DataFrame, visible_cols: list[str]) -> None:
    _render_prompt_col_selector(df, visible_cols)
    _render_native_table(df, visible_cols)


def _render_prompt_col_selector(df: pd.DataFrame, visible_cols: list[str]) -> None:
    """Compact row of toggle buttons above the table — only in LLM Extraction mode."""
    if st.session_state.get("panel_enrichment_type") != "LLM Extraction":
        return

    prompt = st.session_state.get("prompt_textarea", "")
    in_prompt = set(re.findall(r"\{\{(.+?)\}\}", prompt))

    cols_to_show = visible_cols[:20]
    max_per_row = 10
    for row_start in range(0, len(cols_to_show), max_per_row):
        row_slice = cols_to_show[row_start: row_start + max_per_row]
        btn_cols = st.columns(len(row_slice))
        for ci, col in enumerate(row_slice):
            sel = col in in_prompt
            with btn_cols[ci]:
                if st.button(
                    f"✓ {col}" if sel else col,
                    key=f"psel_{col}",
                    use_container_width=True,
                    type="primary" if sel else "secondary",
                ):
                    if sel:
                        st.session_state.prompt_textarea = re.sub(
                            r"\s*\{\{" + re.escape(col) + r"\}\}", "",
                            st.session_state.get("prompt_textarea", ""),
                        ).strip()
                    else:
                        current = st.session_state.get("prompt_textarea", "")
                        st.session_state.prompt_textarea = (current.rstrip() + f" {{{{{col}}}}}").lstrip()
                    st.rerun()


def _render_native_table(df: pd.DataFrame, visible_cols: list[str]) -> None:
    new_cols = st.session_state.get("new_cols", [])
    rename_map = {col: f"{col} ({_fill_pct(df[col])}%)" for col in visible_cols}
    display_df = df[visible_cols].rename(columns=rename_map)

    if new_cols and any(c in visible_cols for c in new_cols):
        renamed_new = [rename_map.get(c, c) for c in new_cols if c in visible_cols]

        def highlight_new(data: pd.DataFrame) -> pd.DataFrame:
            styles = pd.DataFrame("", index=data.index, columns=data.columns)
            for col in renamed_new:
                if col in data.columns:
                    styles[col] = "background-color: #fff9c4"
            return styles

        st.dataframe(
            display_df.style.apply(highlight_new, axis=None),
            hide_index=True,
            use_container_width=True,
            height=TABLE_HEIGHT,
        )
    else:
        st.dataframe(display_df, hide_index=True, use_container_width=True, height=TABLE_HEIGHT)

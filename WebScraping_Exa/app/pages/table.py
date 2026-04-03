import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from app.components.file_browser import render_file_browser
from app.components.enrichment_panel import render_enrichment_panel

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
    _render_fill_remaining_bar(df)
    visible_cols = _get_visible_cols(filtered_df)
    _render_dataframe(filtered_df, visible_cols)

    st.divider()
    render_enrichment_panel(filtered_df)


def _render_row_count(df: pd.DataFrame, filtered_df: pd.DataFrame) -> None:
    if len(filtered_df) != len(df):
        st.caption(f"{len(filtered_df):,} of {len(df):,} rows (filtered)")
    else:
        st.caption(f"{len(df):,} rows")


def _render_fill_remaining_bar(df: pd.DataFrame) -> None:
    """For each generated column with empty rows — show a button to fill them."""
    new_cols = [c for c in st.session_state.get("new_cols", []) if c in df.columns]
    if not new_cols:
        return

    cols_with_empty: list[tuple[str, int]] = []
    for col in new_cols:
        empty = df[col].apply(
            lambda v: pd.isna(v) or str(v).strip() in ("", "nan", "None")
        ).sum()
        if empty > 0:
            cols_with_empty.append((col, int(empty)))

    if not cols_with_empty:
        return

    btn_cols = st.columns(min(len(cols_with_empty), 4))
    for i, (col, n_empty) in enumerate(cols_with_empty):
        with btn_cols[i % 4]:
            if st.button(
                f"{col} — fill {n_empty:,} empty",
                key=f"fill_remaining_{col}",
                use_container_width=True,
            ):
                st.session_state.panel_prefill_fill_col = col
                st.session_state.panel_autorun = True
                components.html(
                    "<script>window.parent.document.querySelector('.main').scrollTop = 999999;</script>",
                    height=0,
                )
                st.rerun()


def _render_toolbar(df: pd.DataFrame) -> None:
    source = st.session_state.get("source_file", "")
    filename = source.replace("\\", "/").split("/")[-1] if source else "untitled"
    n_rows, n_cols = df.shape

    c1, c2 = st.columns([4, 1])
    with c1:
        st.markdown(f"**{filename}** &nbsp; {n_rows:,} rows &nbsp; {n_cols} cols")
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

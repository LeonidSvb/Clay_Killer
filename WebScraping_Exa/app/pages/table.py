import streamlit as st
import pandas as pd
from app.components.file_browser import render_file_browser

OPERATORS = ["=", "!=", ">=", "<=", "contains", "not contains", "is empty", "is not empty"]


def render_table() -> None:
    render_file_browser()

    df: pd.DataFrame | None = st.session_state.get("df")
    if df is None:
        return

    st.divider()
    _render_toolbar(df)

    filtered_df = _apply_filters(df)
    visible_cols = _get_visible_cols(filtered_df)
    _render_dataframe(filtered_df, visible_cols)

    if len(filtered_df) != len(df):
        st.caption(f"Showing {len(filtered_df):,} of {len(df):,} rows (filtered)")

    st.divider()
    _render_run_button()


def _render_toolbar(df: pd.DataFrame) -> None:
    source = st.session_state.get("source_file", "")
    filename = source.replace("\\", "/").split("/")[-1] if source else "untitled"
    n_rows, n_cols = df.shape

    c1, c2, c3, c4 = st.columns([4, 1, 1, 1])
    with c1:
        st.markdown(f"**{filename}** &nbsp; {n_rows:,} rows &nbsp; {n_cols} cols")
    with c2:
        csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            "Download",
            data=csv_bytes,
            file_name=filename,
            mime="text/csv",
            use_container_width=True,
        )
    with c3:
        _render_columns_toggle(df)
    with c4:
        _render_filter_toggle(df)


def _render_columns_toggle(df: pd.DataFrame) -> None:
    all_cols = list(df.columns)
    current = st.session_state.get("visible_cols", all_cols)
    if not current:
        current = all_cols

    with st.popover("Columns", use_container_width=True):
        selected = st.multiselect(
            "Show columns",
            options=all_cols,
            default=[c for c in current if c in all_cols],
            label_visibility="collapsed",
        )
        if st.button("Show all", use_container_width=True):
            st.session_state.visible_cols = all_cols
            st.rerun()
        if selected != st.session_state.get("visible_cols"):
            st.session_state.visible_cols = selected if selected else all_cols
            st.rerun()


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
                result = result[series.isna() | (series.astype(str).str.strip() == "") | (series.astype(str) == "nan")]
            elif op == "is not empty":
                result = result[~(series.isna() | (series.astype(str).str.strip() == "") | (series.astype(str) == "nan"))]
            elif val == "":
                continue
            elif op == "=":
                numeric = pd.to_numeric(series, errors="coerce")
                try:
                    result = result[numeric == float(val)]
                except ValueError:
                    result = result[series.astype(str).str.lower() == val.lower()]
            elif op == "!=":
                numeric = pd.to_numeric(series, errors="coerce")
                try:
                    result = result[numeric != float(val)]
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
    display_df = df[visible_cols]

    if new_cols and any(c in visible_cols for c in new_cols):
        def highlight_new(data: pd.DataFrame) -> pd.DataFrame:
            styles = pd.DataFrame("", index=data.index, columns=data.columns)
            for col in new_cols:
                if col in data.columns:
                    styles[col] = "background-color: #fff9c4"
            return styles
        st.dataframe(
            display_df.style.apply(highlight_new, axis=None),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.dataframe(display_df, hide_index=True, use_container_width=True)


def _render_run_button() -> None:
    if st.button("+ Run Enrichment", type="primary"):
        st.session_state.panel_open = True
        st.rerun()

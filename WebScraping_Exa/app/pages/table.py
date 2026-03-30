import streamlit as st
import pandas as pd
from io import StringIO
from app.components.file_browser import render_file_browser


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
    st.divider()
    _render_run_button()


def _render_toolbar(df: pd.DataFrame) -> None:
    source = st.session_state.get("source_file", "")
    filename = source.split("/")[-1].split("\\")[-1] if source else "untitled"
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
        _render_filter_toggle()


def _render_columns_toggle(df: pd.DataFrame) -> None:
    if "visible_cols" not in st.session_state:
        st.session_state.visible_cols = list(df.columns)

    with st.popover("Columns", use_container_width=True):
        all_cols = list(df.columns)
        selected = st.multiselect(
            "Show columns",
            options=all_cols,
            default=st.session_state.visible_cols,
            label_visibility="collapsed",
        )
        if selected != st.session_state.visible_cols:
            st.session_state.visible_cols = selected
            st.rerun()


def _render_filter_toggle() -> None:
    with st.popover("Filter", use_container_width=True):
        df = st.session_state.df
        if df is None:
            return

        if "filters" not in st.session_state:
            st.session_state.filters = []

        col_options = list(df.columns)
        operator_options = ["=", "!=", ">=", "<=", "contains", "not contains"]

        if st.button("+ Add filter"):
            st.session_state.filters.append({"col": col_options[0], "op": "=", "val": ""})

        filters_to_remove = []
        for i, f in enumerate(st.session_state.filters):
            fc1, fc2, fc3, fc4 = st.columns([3, 2, 3, 1])
            with fc1:
                f["col"] = st.selectbox("Column", col_options, key=f"fc_{i}",
                                         index=col_options.index(f["col"]) if f["col"] in col_options else 0,
                                         label_visibility="collapsed")
            with fc2:
                f["op"] = st.selectbox("Op", operator_options, key=f"fo_{i}",
                                        index=operator_options.index(f["op"]) if f["op"] in operator_options else 0,
                                        label_visibility="collapsed")
            with fc3:
                f["val"] = st.text_input("Value", value=f["val"], key=f"fv_{i}",
                                          label_visibility="collapsed")
            with fc4:
                if st.button("x", key=f"fdel_{i}"):
                    filters_to_remove.append(i)

        for i in reversed(filters_to_remove):
            st.session_state.filters.pop(i)
            st.rerun()


def _apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    filters = st.session_state.get("filters", [])
    result = df.copy()

    for f in filters:
        col, op, val = f.get("col"), f.get("op"), f.get("val", "")
        if not col or col not in result.columns or val == "":
            continue
        try:
            series = result[col]
            if op == "=":
                try:
                    result = result[series == type(series.iloc[0])(val)]
                except Exception:
                    result = result[series.astype(str) == val]
            elif op == "!=":
                try:
                    result = result[series != type(series.iloc[0])(val)]
                except Exception:
                    result = result[series.astype(str) != val]
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
    if not visible:
        visible = available
    return visible


def _render_dataframe(df: pd.DataFrame, visible_cols: list[str]) -> None:
    new_cols = st.session_state.get("new_cols", [])

    def highlight_new(data: pd.DataFrame) -> pd.DataFrame:
        styles = pd.DataFrame("", index=data.index, columns=data.columns)
        for col in new_cols:
            if col in data.columns:
                styles[col] = "background-color: #fff9c4"
        return styles

    display_df = df[visible_cols]

    if new_cols and any(c in visible_cols for c in new_cols):
        st.dataframe(
            display_df.style.apply(highlight_new, axis=None),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.dataframe(display_df, hide_index=True, use_container_width=True)

    if len(df) != len(st.session_state.df):
        st.caption(f"Showing {len(df):,} of {len(st.session_state.df):,} rows (filtered)")


def _render_run_button() -> None:
    if st.button("+ Run Enrichment", type="primary", use_container_width=False):
        st.session_state.panel_open = True
        st.rerun()

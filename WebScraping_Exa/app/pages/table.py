import json
import re
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from app.components.file_browser import render_file_browser
from app.components.enrichment_panel import render_enrichment_panel
from app.components.plusvibe_push import render_plusvibe_push
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
    _render_fill_remaining_bar(df)
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
    render_plusvibe_push(filtered_df)


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
                source = st.session_state.get("source_file")
                if source:
                    try:
                        st.session_state.df.to_csv(source, index=False)
                    except Exception:
                        pass
                st.rerun()


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
    is_llm = st.session_state.get("panel_enrichment_type") == "LLM Extraction"
    if is_llm:
        _render_interactive_table(df, visible_cols)
    else:
        _render_static_table(df, visible_cols)


def _render_static_table(df: pd.DataFrame, visible_cols: list[str]) -> None:
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


def _render_interactive_table(df: pd.DataFrame, visible_cols: list[str]) -> None:
    """HTML table with clickable resizable headers — LLM Extraction mode only."""
    new_cols = set(st.session_state.get("new_cols", []))

    # Process incoming column selection from JS
    raw = st.session_state.get("_col_sel_input", "")
    if raw:
        newly_selected = [c for c in raw.split("|||") if c in visible_cols]
        prompt = st.session_state.get("prompt_textarea", "")
        for col in visible_cols:
            prompt = re.sub(r"\s*\{\{" + re.escape(col) + r"\}\}", "", prompt)
        prompt = prompt.strip()
        for col in newly_selected:
            prompt = (prompt + f" {{{{{col}}}}}").lstrip()
        st.session_state.prompt_textarea = prompt.strip()
        st.session_state["_col_sel_input"] = ""
        st.rerun()

    # Current prompt selection
    prompt = st.session_state.get("prompt_textarea", "")
    in_prompt = set(re.findall(r"\{\{(.+?)\}\}", prompt))

    # Build column metadata
    cols_meta = [
        {
            "name": col,
            "label": f"{col} ({_fill_pct(df[col])}%)",
            "is_new": col in new_cols,
            "selected": col in in_prompt,
        }
        for col in visible_cols
    ]

    # Build rows (cap at 1000 for performance)
    rows_data = []
    for i in range(min(len(df), 1000)):
        row = df.iloc[i]
        rows_data.append([
            "" if str(row.get(col, "")) in ("nan", "None") else str(row.get(col, ""))
            for col in visible_cols
        ])

    cols_json = json.dumps(cols_meta)
    rows_json = json.dumps(rows_data)

    # Hidden input (CSS-collapsed)
    st.text_input("col_sel", key="_col_sel_input", label_visibility="collapsed")
    st.markdown(
        "<style>div:has(>div>input[aria-label='col_sel'])"
        "{height:0!important;overflow:hidden;margin:0!important;padding:0!important}</style>",
        unsafe_allow_html=True,
    )

    html_code = f"""
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:transparent}}
  .wrap{{height:{TABLE_HEIGHT}px;overflow:auto;border:1px solid #e0e0e0;border-radius:4px}}
  table{{border-collapse:collapse;table-layout:fixed;width:max-content;min-width:100%}}
  thead tr th{{position:sticky;top:0;z-index:10}}
  th{{
    position:relative;padding:7px 20px 7px 10px;
    border:1px solid #e0e0e0;background:#f8f9fa;
    font-size:11.5px;font-weight:600;color:#555;
    text-align:left;cursor:pointer;user-select:none;
    white-space:nowrap;overflow:hidden;min-width:80px;width:160px
  }}
  th:hover{{background:#eef2ff;color:#333}}
  th.selected{{background:#dbeafe;color:#1d4ed8;border-color:#93c5fd}}
  th.selected:hover{{background:#bfdbfe}}
  th.new-col{{background:#fef9c3}}
  th.new-col.selected{{background:#dbeafe}}
  .resizer{{
    position:absolute;right:0;top:0;bottom:0;width:5px;
    cursor:col-resize;z-index:1
  }}
  .resizer:hover,.resizer.active{{background:#93c5fd}}
  td{{
    padding:6px 10px;border:1px solid #efefef;
    font-size:12px;color:#333;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
    max-width:220px;cursor:default;
  }}
  td.expanded{{
    white-space:pre-wrap;overflow:visible;max-width:400px;
    background:#fffbea!important;z-index:5;position:relative;
    box-shadow:0 2px 8px rgba(0,0,0,.15);
  }}
  td.new-col{{background:#fef9c3!important}}
  td.selected{{background:#eff6ff}}
  td.new-col.selected{{background:#dbeafe}}
  tr:nth-child(even) td{{background:#fafafa}}
  tr:nth-child(even) td.selected{{background:#eff6ff}}
</style>
<div class="wrap">
  <table><thead><tr id="hrow"></tr></thead><tbody id="tbody"></tbody></table>
</div>
<script>
const COLS = {cols_json};
const ROWS = {rows_json};
let selected = new Set(COLS.filter(c=>c.selected).map(c=>c.name));

function sendToStreamlit(){{
  const val = [...selected].join("|||");
  const input = window.parent.document.querySelector('input[aria-label="col_sel"]');
  if(!input) return;
  Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')
        .set.call(input, val);
  input.dispatchEvent(new Event('input',{{bubbles:true}}));
}}

function refreshCells(){{
  document.querySelectorAll("td[data-col]").forEach(td=>{{
    td.classList.toggle("selected", selected.has(td.dataset.col));
  }});
}}

// Build headers
const hrow = document.getElementById("hrow");
COLS.forEach((col,i)=>{{
  const th = document.createElement("th");
  if(col.selected) th.classList.add("selected");
  if(col.is_new)   th.classList.add("new-col");
  th.textContent = col.label;

  th.addEventListener("click", e=>{{
    if(e.target.classList.contains("resizer")) return;
    if(e.ctrlKey||e.metaKey){{
      selected.has(col.name) ? selected.delete(col.name) : selected.add(col.name);
    }} else {{
      if(selected.has(col.name) && selected.size===1){{
        selected.clear();
      }} else {{
        selected.clear();
        selected.add(col.name);
      }}
    }}
    hrow.querySelectorAll("th").forEach((t,j)=>{{
      t.classList.toggle("selected", selected.has(COLS[j].name));
    }});
    refreshCells();
    sendToStreamlit();
  }});

  const resizer = document.createElement("div");
  resizer.className = "resizer";
  th.appendChild(resizer);
  let startX, startW;
  resizer.addEventListener("mousedown", e=>{{
    e.preventDefault(); e.stopPropagation();
    startX=e.pageX; startW=th.offsetWidth;
    resizer.classList.add("active");
    const onMove=e=>{{ th.style.width=Math.max(60,startW+e.pageX-startX)+"px"; }};
    const onUp=()=>{{
      resizer.classList.remove("active");
      document.removeEventListener("mousemove",onMove);
      document.removeEventListener("mouseup",onUp);
    }};
    document.addEventListener("mousemove",onMove);
    document.addEventListener("mouseup",onUp);
  }});

  hrow.appendChild(th);
}});

// Build rows
const tbody = document.getElementById("tbody");
ROWS.forEach(row=>{{
  const tr = document.createElement("tr");
  COLS.forEach((col,i)=>{{
    const td = document.createElement("td");
    td.dataset.col = col.name;
    td.textContent = row[i];
    if(col.is_new) td.classList.add("new-col");
    if(selected.has(col.name)) td.classList.add("selected");
    td.addEventListener("dblclick", ()=>{{
      td.classList.toggle("expanded");
    }});
    tr.appendChild(td);
  }});
  tbody.appendChild(tr);
}});
</script>
"""

    components.html(html_code, height=TABLE_HEIGHT + 42, scrolling=False)

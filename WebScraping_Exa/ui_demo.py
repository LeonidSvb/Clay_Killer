"""
ui_demo.py — кастомная HTML таблица: кликабельные хедеры, ресайз, Ctrl+multi-select.
Запуск: streamlit run ui_demo.py
"""

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(layout="wide")

COLS = ["First Name", "Company Name", "Website", "Email"]

DATA = [
    {"First Name": "John Smith",   "Company Name": "Acme Corp",      "Website": "acme.io",      "Email": "john@acme.io"},
    {"First Name": "Sara Lee",     "Company Name": "Blue Sky Ltd",   "Website": "bluesky.com",  "Email": "sara@bluesky.com"},
    {"First Name": "Mike Johnson", "Company Name": "TechStart",      "Website": "techstart.io", "Email": "mike@techstart.io"},
    {"First Name": "Anna Brown",   "Company Name": "GrowthCo",       "Website": "growthco.com", "Email": "anna@growthco.com"},
    {"First Name": "Paul Davis",   "Company Name": "Nexus Inc",      "Website": "nexus.io",     "Email": "paul@nexus.io"},
]

if "selected_cols" not in st.session_state:
    st.session_state.selected_cols = []

# hidden input — получаем список выбранных колонок от JS
raw = st.text_input("_sel", value="", key="_col_sel", label_visibility="hidden")
if raw:
    cols = [c.strip() for c in raw.split("|||") if c.strip() in COLS]
    st.session_state.selected_cols = cols
    st.session_state["_col_sel"] = ""
    st.rerun()

selected = st.session_state.selected_cols

if selected:
    prompt = " ".join(f"{{{{{c}}}}}" for c in COLS if c in selected)
    st.info(f"Промпт: {prompt}")
else:
    st.caption("Кликни заголовок чтобы добавить колонку в промпт. Ctrl+клик — несколько.")

cols_json = str(COLS).replace("'", '"')
sel_json  = str(selected).replace("'", '"')

rows_html = "".join(
    "<tr>" + "".join(f"<td data-col='{c}'>{row[c]}</td>" for c in COLS) + "</tr>"
    for row in DATA
)

html = f"""
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: transparent; }}
  .wrap {{ overflow-x: auto; border: 1px solid #e0e0e0; border-radius: 6px; }}
  table {{ border-collapse: collapse; table-layout: fixed; width: 100%; }}

  th {{
    position: relative;
    padding: 8px 12px;
    border: 1px solid #e0e0e0;
    background: #f8f9fa;
    font-size: 12px;
    font-weight: 600;
    color: #555;
    text-align: left;
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
    overflow: hidden;
    min-width: 80px;
  }}
  th:hover {{ background: #eef2ff; color: #333; }}
  th.selected {{ background: #dbeafe; color: #1d4ed8; border-color: #93c5fd; }}
  th.selected:hover {{ background: #bfdbfe; }}

  .resizer {{
    position: absolute;
    right: 0; top: 0; bottom: 0;
    width: 5px;
    cursor: col-resize;
    background: transparent;
    z-index: 1;
  }}
  .resizer:hover, .resizer.active {{ background: #93c5fd; }}

  td {{
    padding: 7px 12px;
    border: 1px solid #e0e0e0;
    font-size: 12px;
    color: #333;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  td.selected {{ background: #eff6ff; }}
  tr:nth-child(even) td {{ background: #fafafa; }}
  tr:nth-child(even) td.selected {{ background: #eff6ff; }}
</style>

<div class="wrap">
  <table id="tbl">
    <thead><tr id="hrow"></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>

<script>
const COLS = {cols_json};
let selected = new Set({sel_json});

const hrow = document.getElementById("hrow");

function sendToStreamlit() {{
  const val = [...selected].join("|||");
  const input = window.parent.document.querySelector('input[aria-label="_sel"]');
  if (!input) return;
  Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')
        .set.call(input, val);
  input.dispatchEvent(new Event('input', {{ bubbles: true }}));
}}

function refreshCells() {{
  document.querySelectorAll("td").forEach(td => {{
    td.classList.toggle("selected", selected.has(td.dataset.col));
  }});
}}

COLS.forEach((col, i) => {{
  const th = document.createElement("th");
  th.style.width = "160px";
  th.textContent = col;
  if (selected.has(col)) th.classList.add("selected");

  // click to select
  th.addEventListener("click", e => {{
    if (e.target.classList.contains("resizer")) return;
    if (e.ctrlKey || e.metaKey) {{
      selected.has(col) ? selected.delete(col) : selected.add(col);
    }} else {{
      if (selected.has(col) && selected.size === 1) {{
        selected.clear();
      }} else {{
        selected.clear();
        selected.add(col);
      }}
    }}
    hrow.querySelectorAll("th").forEach((t, j) => {{
      t.classList.toggle("selected", selected.has(COLS[j]));
    }});
    refreshCells();
    sendToStreamlit();
  }});

  // resize handle
  const resizer = document.createElement("div");
  resizer.className = "resizer";
  th.appendChild(resizer);

  let startX, startW;
  resizer.addEventListener("mousedown", e => {{
    e.preventDefault();
    e.stopPropagation();
    startX = e.pageX;
    startW = th.offsetWidth;
    resizer.classList.add("active");

    const onMove = e => {{
      const w = Math.max(60, startW + e.pageX - startX);
      th.style.width = w + "px";
    }};
    const onUp = () => {{
      resizer.classList.remove("active");
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    }};
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }});

  hrow.appendChild(th);
}});

refreshCells();
</script>
"""

components.html(html, height=280, scrolling=False)

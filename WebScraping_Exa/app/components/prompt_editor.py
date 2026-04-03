"""
app/components/prompt_editor.py — Side-by-side prompt editor with live preview.

Layout:
  [Boolean] [Score 0-10] [Extract] [Full profile]   — template starters
  ┌──────────────────────┬─────────────────────────┐
  │ col chips (3/row)    │ Live preview — row 1     │
  │ textarea (editable)  │ Variable inspector ✓/✗   │
  │                      │ JSON suffix preview      │
  └──────────────────────┴─────────────────────────┘
"""

import re

import pandas as pd
import streamlit as st

from app.enrichments.llm import (
    render_prompt_preview,
    JSON_SUFFIXES,
)

_STARTERS: dict[str, str] = {
    "Boolean": "Is {{Company Name}} a [YOUR CRITERIA]?",
    "Score": "How well does {{Company Name}} fit [YOUR CRITERIA]?\nRate from 0 to 10.",
    "Extract": "Extract [WHAT] from {{Company Name}}.\n\nInfo: {{Website Summary}}",
    "Profile": "Analyze {{Company Name}}.\n\nWebsite: {{Website}}\nInfo: {{Website Summary}}",
}

_DEFAULT_TEXT = "Is {{Company Name}} a [YOUR CRITERIA]?"


def _fill_pct(series: pd.Series) -> int:
    total = len(series)
    if total == 0:
        return 0
    empty = series.isna().sum() + (
        series.astype(str).str.strip().isin(["", "nan", "None"])
    ).sum()
    return round((total - min(int(empty), total)) / total * 100)


def _find_preview_row(df: pd.DataFrame, referenced_cols: list[str]) -> pd.Series:
    """Return first row where all referenced columns are non-empty."""
    for i in range(min(len(df), 50)):
        row = df.iloc[i]
        if all(
            str(row.get(c, "")).strip() not in ("", "nan", "None")
            for c in referenced_cols
            if c in df.columns
        ):
            return row
    return df.iloc[0]


def render_prompt_editor(df: pd.DataFrame | None = None, output_type: str = "Extract") -> str:
    """
    Renders side-by-side prompt editor.
    Returns current prompt text.
    """
    # Initialize textarea on first load
    if "prompt_textarea" not in st.session_state:
        st.session_state.prompt_textarea = _DEFAULT_TEXT

    # Template starter buttons
    s_cols = st.columns(4)
    for col_obj, (name, text) in zip(s_cols, _STARTERS.items()):
        with col_obj:
            if st.button(name, use_container_width=True, key=f"tpl_{name}"):
                st.session_state.prompt_textarea = text
                st.rerun()

    # Side-by-side
    col_edit, col_preview = st.columns([1, 1], gap="small")

    with col_edit:
        # Column chips — compact, 3 per row
        if df is not None and not df.empty:
            cols = list(df.columns)
            chips_per_row = 3
            for row_start in range(0, len(cols), chips_per_row):
                row_cols = cols[row_start: row_start + chips_per_row]
                chip_containers = st.columns(len(row_cols))
                for ci, col in enumerate(row_cols):
                    with chip_containers[ci]:
                        if st.button(
                            col[:14],
                            key=f"chip_{col}",
                            use_container_width=True,
                            help=col,
                        ):
                            current = st.session_state.get("prompt_textarea", "")
                            st.session_state.prompt_textarea = current + " {{" + col + "}}"
                            st.rerun()

        # Always-editable textarea
        st.text_area(
            "prompt",
            height=200,
            key="prompt_textarea",
            label_visibility="collapsed",
            placeholder="Write your question here. Use {{Column Name}} to insert data.",
        )

    with col_preview:
        current_text = st.session_state.get("prompt_textarea", "")
        found_cols = re.findall(r"\{\{(.+?)\}\}", current_text)

        if df is not None and not df.empty:
            preview_row = _find_preview_row(df, found_cols)

            # Live preview of rendered prompt
            rendered = render_prompt_preview(current_text, df, preview_row)
            st.code(rendered, language=None)

            # JSON suffix preview (greyed out)
            suffix_preview = JSON_SUFFIXES.get(output_type, JSON_SUFFIXES["Extract"])
            st.caption(f"+ auto-appended: `{suffix_preview.strip()}`")

            # Variable inspector
            if found_cols:
                for col_ref in found_cols:
                    if col_ref in df.columns:
                        pct = _fill_pct(df[col_ref])
                        val = str(preview_row.get(col_ref, ""))
                        display = val[:50] if val not in ("nan", "None", "") else "(empty in this row)"
                        st.caption(f"✓ {col_ref} — {display} · {pct}% filled")
                    else:
                        st.markdown(f":red[✗ `{col_ref}` — column not found]")
        else:
            st.caption("Load a CSV to see live preview")

    return current_text

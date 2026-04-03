"""
app/components/prompt_editor.py — Prompt editor with always-editable textarea.

Flow:
  - Dropdown loads a saved prompt into textarea (optional)
  - Textarea is always editable — run without saving
  - "Save as..." button asks for a name and saves
  - Delete button removes a saved prompt
"""

import re
from pathlib import Path

import pandas as pd
import streamlit as st

from app.enrichments.llm import (
    list_enrichment_prompts,
    load_enrichment_prompt,
    save_enrichment_prompt,
    delete_enrichment_prompt,
    render_prompt_preview,
)

_DEFAULT_TEMPLATE = (
    'Analyze the company below and return structured JSON.\n\n'
    'Company: {{Company Name}}\n'
    'Website: {{Website}}\n\n'
    'Return JSON: {"field": "value", "confidence": <0-10>}'
)


def _sanitize_name(raw: str) -> str:
    clean = re.sub(r'[^\w]', '_', raw.strip())
    clean = re.sub(r'_+', '_', clean).strip('_')
    return clean[:80]


def render_prompt_editor(df: pd.DataFrame | None = None) -> str:
    """
    Renders prompt editor UI.
    Returns current prompt text (not a filename).
    """
    prompts = list_enrichment_prompts()

    # Initialize textarea content on first load
    if "prompt_textarea" not in st.session_state:
        if prompts:
            template, _ = load_enrichment_prompt(prompts[0])
            st.session_state.prompt_textarea = template
            st.session_state._last_loaded_prompt = prompts[0]
        else:
            st.session_state.prompt_textarea = _DEFAULT_TEMPLATE
            st.session_state._last_loaded_prompt = None

    # Row: Load dropdown + Delete button
    c_dd, c_del = st.columns([5, 1])

    with c_dd:
        load_options = ["— select saved —"] + prompts
        saved_sel = st.selectbox(
            "load_prompt",
            load_options,
            key="prompt_load_select",
            label_visibility="collapsed",
        )

    with c_del:
        del_clicked = st.button("Del", use_container_width=True, key="btn_del_prompt")

    # Load selected prompt into textarea (on change)
    if saved_sel != "— select saved —":
        if saved_sel != st.session_state.get("_last_loaded_prompt"):
            template, _ = load_enrichment_prompt(saved_sel)
            st.session_state.prompt_textarea = template
            st.session_state._last_loaded_prompt = saved_sel
            st.rerun()

    # Delete dialog
    if del_clicked:
        if saved_sel == "— select saved —":
            st.warning("Select a prompt to delete.")
        else:
            st.session_state.show_delete_prompt = True

    if st.session_state.get("show_delete_prompt") and saved_sel != "— select saved —":
        st.warning(f"Delete '{saved_sel}'? This cannot be undone.")
        confirm = st.text_input("Type 'delete' to confirm:", key="delete_confirm")
        dc1, dc2 = st.columns(2)
        with dc1:
            if st.button("Confirm", use_container_width=True, key="btn_del_confirm") and confirm == "delete":
                delete_enrichment_prompt(saved_sel)
                st.session_state.show_delete_prompt = False
                st.session_state._last_loaded_prompt = None
                st.session_state.prompt_textarea = _DEFAULT_TEMPLATE
                st.rerun()
        with dc2:
            if st.button("Cancel", use_container_width=True, key="btn_del_cancel"):
                st.session_state.show_delete_prompt = False
                st.rerun()

    # Always-editable textarea
    st.text_area(
        "prompt_body",
        height=180,
        key="prompt_textarea",
        label_visibility="collapsed",
    )

    # Column chips
    if df is not None and not df.empty:
        st.caption("Insert column:")
        cols = list(df.columns)
        chips_per_row = 4
        for row_start in range(0, len(cols), chips_per_row):
            row_cols = cols[row_start: row_start + chips_per_row]
            chip_containers = st.columns(len(row_cols))
            for ci, col in enumerate(row_cols):
                with chip_containers[ci]:
                    if st.button(col, key=f"chip_{col}", use_container_width=True):
                        current = st.session_state.get("prompt_textarea", "")
                        st.session_state.prompt_textarea = current + "{{" + col + "}}"
                        st.rerun()

    # Save as...
    if st.button("Save as...", key="btn_save_as"):
        st.session_state.show_save_as = not st.session_state.get("show_save_as", False)

    if st.session_state.get("show_save_as"):
        save_name_raw = st.text_input(
            "Prompt name:",
            key="save_as_name_input",
            placeholder="my_icp_filter",
        )
        sa1, sa2 = st.columns(2)
        with sa1:
            if st.button("Save", type="primary", use_container_width=True, key="btn_save_as_confirm"):
                if save_name_raw.strip():
                    clean = _sanitize_name(save_name_raw)
                    save_enrichment_prompt(clean, st.session_state.get("prompt_textarea", ""))
                    st.session_state._last_loaded_prompt = clean
                    st.session_state.show_save_as = False
                    st.success(f"Saved as '{clean}'")
                    st.rerun()
                else:
                    st.error("Enter a name.")
        with sa2:
            if st.button("Cancel", use_container_width=True, key="btn_save_as_cancel"):
                st.session_state.show_save_as = False
                st.rerun()

    # Preview (row 1)
    if df is not None and not df.empty:
        with st.expander("Preview (row 1)", expanded=False):
            preview = render_prompt_preview(st.session_state.get("prompt_textarea", ""), df)
            st.code(preview, language=None)

    return st.session_state.get("prompt_textarea", "")

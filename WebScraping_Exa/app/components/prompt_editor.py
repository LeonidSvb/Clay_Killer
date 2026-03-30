"""
app/components/prompt_editor.py — Prompt selector + editor with {{column}} chips.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from app.enrichments.llm import (
    list_enrichment_prompts,
    load_enrichment_prompt,
    save_enrichment_prompt,
    delete_enrichment_prompt,
    render_prompt_preview,
    ENRICHMENT_PROMPTS_DIR,
)


def _init_prompt_state(name: str) -> None:
    template, _ = load_enrichment_prompt(name)
    st.session_state.prompt_text = template
    st.session_state.prompt_edit_mode = False


def render_prompt_editor(df: pd.DataFrame | None = None) -> str:
    """
    Renders prompt selector + editor UI.
    Returns currently selected prompt name.
    """
    prompts = list_enrichment_prompts()
    if not prompts:
        prompts = ["company_full"]

    # Row 1: selector + action buttons
    c_sel, c_edit, c_new, c_del = st.columns([4, 1, 1, 1])

    with c_sel:
        current = st.session_state.get("current_prompt_name")
        if current not in prompts:
            current = prompts[0]
            st.session_state.current_prompt_name = current
            _init_prompt_state(current)

        idx = prompts.index(current)
        selected = st.selectbox(
            "prompt", prompts, index=idx,
            label_visibility="collapsed",
            key="prompt_selector",
        )
        if selected != st.session_state.get("current_prompt_name"):
            st.session_state.current_prompt_name = selected
            _init_prompt_state(selected)
            st.rerun()

    with c_edit:
        if st.button("Edit", use_container_width=True, key="btn_edit_prompt"):
            if "prompt_text" not in st.session_state:
                _init_prompt_state(selected)
            st.session_state.prompt_edit_mode = True

    with c_new:
        if st.button("+ New", use_container_width=True, key="btn_new_prompt"):
            st.session_state.show_new_prompt = True

    with c_del:
        if st.button("Delete", use_container_width=True, key="btn_del_prompt"):
            st.session_state.show_delete_prompt = True

    # New prompt dialog
    if st.session_state.get("show_new_prompt"):
        new_name = st.text_input(
            "New prompt name (letters, numbers, underscores):",
            key="new_prompt_name",
        )
        cc1, cc2 = st.columns(2)
        with cc1:
            if st.button("Create", use_container_width=True, key="btn_create_confirm") and new_name.strip():
                clean = new_name.strip().replace(" ", "_")
                default_content = (
                    "Analyze the company below and return structured JSON.\n\n"
                    "Company: {{Company Name}}\n"
                    "Website: {{Website}}\n\n"
                    'Return JSON: {"field": "value", "confidence": <0-10>}'
                )
                save_enrichment_prompt(clean, default_content)
                st.session_state.current_prompt_name = clean
                st.session_state.prompt_text = default_content
                st.session_state.prompt_edit_mode = True
                st.session_state.show_new_prompt = False
                st.rerun()
        with cc2:
            if st.button("Cancel", use_container_width=True, key="btn_create_cancel"):
                st.session_state.show_new_prompt = False
                st.rerun()

    # Delete confirm dialog
    if st.session_state.get("show_delete_prompt"):
        st.warning(f"Delete prompt '{selected}'? This cannot be undone.")
        confirm = st.text_input("Type 'delete' to confirm:", key="delete_confirm")
        dc1, dc2 = st.columns(2)
        with dc1:
            if st.button("Confirm", use_container_width=True, key="btn_del_confirm") and confirm == "delete":
                deleted = delete_enrichment_prompt(selected)
                st.session_state.show_delete_prompt = False
                refreshed = list_enrichment_prompts()
                st.session_state.current_prompt_name = refreshed[0] if refreshed else ""
                if refreshed:
                    _init_prompt_state(refreshed[0])
                st.rerun()
        with dc2:
            if st.button("Cancel", use_container_width=True, key="btn_del_cancel"):
                st.session_state.show_delete_prompt = False
                st.rerun()

    # Prompt textarea
    edit_mode = st.session_state.get("prompt_edit_mode", False)
    if "prompt_text" not in st.session_state:
        _init_prompt_state(selected)

    current_text = st.session_state.get("prompt_text", "")

    new_text = st.text_area(
        "prompt_body",
        value=current_text,
        height=180,
        disabled=not edit_mode,
        key="prompt_textarea",
        label_visibility="collapsed",
    )
    if edit_mode:
        st.session_state.prompt_text = new_text

    # Column chips (only in edit mode)
    if edit_mode and df is not None and not df.empty:
        st.caption("Insert column:")
        cols = list(df.columns)
        chips_per_row = 4
        for row_start in range(0, len(cols), chips_per_row):
            row_cols = cols[row_start: row_start + chips_per_row]
            chip_containers = st.columns(len(row_cols))
            for ci, col in enumerate(row_cols):
                with chip_containers[ci]:
                    if st.button(col, key=f"chip_{col}", use_container_width=True):
                        st.session_state.prompt_text = (
                            st.session_state.get("prompt_text", "") + "{{" + col + "}}"
                        )
                        st.rerun()

    # Save / Cancel buttons in edit mode
    if edit_mode:
        sb1, sb2 = st.columns(2)
        with sb1:
            if st.button("Save prompt", use_container_width=True, key="btn_save_prompt"):
                save_enrichment_prompt(selected, st.session_state.prompt_text)
                st.session_state.prompt_edit_mode = False
                st.success("Saved")
        with sb2:
            if st.button("Cancel edit", use_container_width=True, key="btn_cancel_edit"):
                _init_prompt_state(selected)
                st.rerun()

    # Preview (row 1 of loaded CSV)
    if df is not None and not df.empty:
        with st.expander("Preview (row 1)", expanded=False):
            preview = render_prompt_preview(st.session_state.get("prompt_text", ""), df)
            st.code(preview, language=None)

    return selected

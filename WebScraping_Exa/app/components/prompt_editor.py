"""
app/components/prompt_editor.py — Side-by-side prompt editor with live preview + prompt library.

Layout:
  [ Select saved prompt ▼ ] [+ New]   name: [editable]   [Update] [Delete]
  [Boolean] [Score 0-10] [Extract] [Full profile]   — template starters
  ┌──────────────────────┬─────────────────────────┐
  │ col chips (6/row)    │ Live preview — row 1     │
  │ textarea (editable)  │ Variable inspector ✓/✗   │
  │                      │ JSON suffix preview      │
  └──────────────────────┴─────────────────────────┘
"""

import re
from pathlib import Path

import pandas as pd
import streamlit as st

from app.enrichments.llm import (
    render_prompt_preview,
    JSON_SUFFIXES,
    get_json_suffix,
    list_enrichment_prompts,
    load_enrichment_prompt,
    save_enrichment_prompt,
    delete_enrichment_prompt,
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


def _render_prompt_library() -> None:
    """Prompt library: load, save, rename, delete saved prompts."""
    saved = list_enrichment_prompts()

    # Backup current textarea so filter reruns don't lose it
    current_text = st.session_state.get("prompt_textarea", _DEFAULT_TEXT)
    st.session_state["_prompt_backup"] = current_text

    lib_col, new_col = st.columns([5, 1])

    with lib_col:
        options = ["— select saved prompt —"] + saved
        loaded_name = st.session_state.get("_loaded_prompt_name", "")
        default_idx = (saved.index(loaded_name) + 1) if loaded_name in saved else 0

        selected = st.selectbox(
            "Saved prompts",
            options,
            index=default_idx,
            key="_prompt_select",
            label_visibility="collapsed",
        )

        if selected != "— select saved prompt —" and selected != st.session_state.get("_loaded_prompt_name"):
            text, _ = load_enrichment_prompt(selected)
            st.session_state.prompt_textarea = text
            st.session_state["_loaded_prompt_name"] = selected
            st.session_state["_loaded_prompt_text"] = text
            st.session_state.pop("_confirm_delete", None)
            st.rerun()

    with new_col:
        if st.button("+ New", use_container_width=True, key="_btn_new_prompt"):
            st.session_state.prompt_textarea = _DEFAULT_TEXT
            st.session_state["_loaded_prompt_name"] = ""
            st.session_state["_loaded_prompt_text"] = ""
            st.session_state.pop("_confirm_delete", None)
            st.rerun()

    # Show name editor + Update/Delete only when a prompt is loaded
    loaded_name = st.session_state.get("_loaded_prompt_name", "")
    loaded_text = st.session_state.get("_loaded_prompt_text", "")

    if loaded_name:
        name_col, upd_col, del_col = st.columns([4, 1, 1])

        with name_col:
            new_name = st.text_input(
                "Prompt name",
                value=loaded_name,
                key="_prompt_name_input",
                label_visibility="collapsed",
                placeholder="Prompt name",
            )

        is_modified = (current_text != loaded_text) or (new_name.strip() != loaded_name)

        with upd_col:
            if st.button(
                "Update" + (" ●" if is_modified else ""),
                use_container_width=True,
                key="_btn_update",
                type="primary" if is_modified else "secondary",
                disabled=not is_modified,
            ):
                clean_name = new_name.strip()
                if clean_name and clean_name != loaded_name:
                    delete_enrichment_prompt(loaded_name)
                save_enrichment_prompt(clean_name or loaded_name, current_text)
                st.session_state["_loaded_prompt_name"] = clean_name or loaded_name
                st.session_state["_loaded_prompt_text"] = current_text
                st.rerun()

        with del_col:
            confirming = st.session_state.get("_confirm_delete", False)
            if confirming:
                if st.button("Sure?", use_container_width=True, key="_btn_del_confirm", type="primary"):
                    delete_enrichment_prompt(loaded_name)
                    st.session_state.prompt_textarea = _DEFAULT_TEXT
                    st.session_state["_loaded_prompt_name"] = ""
                    st.session_state["_loaded_prompt_text"] = ""
                    st.session_state.pop("_confirm_delete", None)
                    st.rerun()
            else:
                if st.button("Delete", use_container_width=True, key="_btn_delete"):
                    st.session_state["_confirm_delete"] = True
                    st.rerun()

    elif saved:
        # No prompt loaded, show save-as for current textarea
        sa_col, sa_btn = st.columns([4, 2])
        with sa_col:
            save_name = st.text_input(
                "Save as", key="_save_as_name",
                label_visibility="collapsed",
                placeholder="Name this prompt to save...",
            )
        with sa_btn:
            if st.button("Save", use_container_width=True, key="_btn_save_new",
                         disabled=not save_name.strip()):
                save_enrichment_prompt(save_name.strip(), current_text)
                st.session_state["_loaded_prompt_name"] = save_name.strip()
                st.session_state["_loaded_prompt_text"] = current_text
                st.rerun()
    else:
        # No saved prompts at all
        sa_col, sa_btn = st.columns([4, 2])
        with sa_col:
            save_name = st.text_input(
                "Save as", key="_save_as_name",
                label_visibility="collapsed",
                placeholder="Name this prompt to save...",
            )
        with sa_btn:
            if st.button("Save", use_container_width=True, key="_btn_save_new",
                         disabled=not save_name.strip()):
                save_enrichment_prompt(save_name.strip(), current_text)
                st.session_state["_loaded_prompt_name"] = save_name.strip()
                st.session_state["_loaded_prompt_text"] = current_text
                st.rerun()


def render_prompt_editor(df: pd.DataFrame | None = None, output_type: str = "Extract") -> str:
    """Renders prompt library + side-by-side editor. Returns current prompt text."""

    # Restore from backup if textarea was reset by a rerun
    if "prompt_textarea" not in st.session_state:
        backup = st.session_state.get("_prompt_backup", _DEFAULT_TEXT)
        st.session_state.prompt_textarea = backup

    # Prompt library
    _render_prompt_library()

    # Template starter buttons
    s_cols = st.columns(4)
    for col_obj, (name, text) in zip(s_cols, _STARTERS.items()):
        with col_obj:
            if st.button(name, use_container_width=True, key=f"tpl_{name}"):
                st.session_state.prompt_textarea = text
                st.session_state["_loaded_prompt_name"] = ""
                st.session_state["_loaded_prompt_text"] = ""
                st.rerun()

    # Side-by-side
    col_edit, col_preview = st.columns([1, 1], gap="small")

    with col_edit:
        # Column chips — 6 per row, table order, fill% shown
        if df is not None and not df.empty:
            cols = list(df.columns)
            chips_per_row = 6
            for row_start in range(0, len(cols), chips_per_row):
                row_cols = cols[row_start: row_start + chips_per_row]
                chip_containers = st.columns(len(row_cols))
                for ci, col in enumerate(row_cols):
                    pct = _fill_pct(df[col])
                    with chip_containers[ci]:
                        if st.button(
                            f"{col[:10]} {pct}%",
                            key=f"chip_{col}",
                            use_container_width=True,
                            help=col,
                        ):
                            current = st.session_state.get("prompt_textarea", "")
                            st.session_state.prompt_textarea = current + " {{" + col + "}}"
                            st.rerun()

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

            rendered = render_prompt_preview(current_text, df, preview_row)
            st.code(rendered, language=None)

            include_reasoning = st.session_state.get("include_reasoning", False)
            suffix_preview = get_json_suffix(output_type, include_reasoning)
            st.caption(f"+ auto-appended: `{suffix_preview.strip()}`")

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

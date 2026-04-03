"""
app/components/prompt_editor.py — Prompt editor with live preview + prompt library.

Layout:
  [ Select prompt ▼ ] [New]
  [ Update * ] [ Save as new ]  ← only when dirty
  ┌──────────────────────┬─────────────────────────────────────────┐
  │ textarea (editable)  │ [Next sample]                           │
  │                      │ Live preview — rendered prompt           │
  │                      │ Variable inspector ✓/✗                  │
  └──────────────────────┴─────────────────────────────────────────┘
"""

import random
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from app.enrichments.llm import (
    render_prompt_preview,
    list_enrichment_prompts,
    load_enrichment_prompt,
    save_enrichment_prompt,
    delete_enrichment_prompt,
)

_DEFAULT_TEXT = "Is {{Company Name}} a [YOUR CRITERIA]?\n\nReturn JSON only: {\"result\": true, \"confidence\": <1-10>}"


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


def _is_empty_row(row: pd.Series) -> bool:
    """True if the row has no non-empty values at all."""
    return all(str(v).strip() in ("", "nan", "None") for v in row.values)


def _render_delete_btn(loaded_name: str) -> None:
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
        if st.button("Del", use_container_width=True, key="_btn_delete"):
            st.session_state["_confirm_delete"] = True
            st.rerun()


def _render_prompt_library() -> None:
    saved = list_enrichment_prompts()
    current_text = st.session_state.get("prompt_textarea", _DEFAULT_TEXT)
    loaded_name = st.session_state.get("_loaded_prompt_name", "")
    loaded_text = st.session_state.get("_loaded_prompt_text", "")
    is_dirty = bool(loaded_name) and (current_text != loaded_text)
    saveas_mode = st.session_state.get("_saveas_mode", False)

    # ── Row 1: dropdown + New ──────────────────────────────────────────────────
    drop_col, new_col = st.columns([5, 1])

    with drop_col:
        options = ["— select prompt —"] + saved
        default_idx = (saved.index(loaded_name) + 1) if loaded_name in saved else 0
        selected = st.selectbox(
            "Prompts", options, index=default_idx,
            key="_prompt_select", label_visibility="collapsed",
        )
        if selected != "— select prompt —" and selected != loaded_name:
            text, *_ = load_enrichment_prompt(selected)
            st.session_state.prompt_textarea = text
            st.session_state["_loaded_prompt_name"] = selected
            st.session_state["_loaded_prompt_text"] = text
            st.session_state.pop("_saveas_mode", None)
            st.session_state.pop("_confirm_delete", None)
            st.rerun()

    with new_col:
        if st.button("New", use_container_width=True, key="_btn_new"):
            st.session_state.prompt_textarea = _DEFAULT_TEXT
            st.session_state["_loaded_prompt_name"] = ""
            st.session_state["_loaded_prompt_text"] = ""
            st.session_state.pop("_saveas_mode", None)
            st.session_state.pop("_confirm_delete", None)
            st.rerun()

    # ── Row 2: context-sensitive actions ──────────────────────────────────────
    if not loaded_name:
        # No prompt loaded → show name input + Save
        sa_col, sa_btn = st.columns([5, 1])
        with sa_col:
            save_name = st.text_input(
                "Save", key="_save_as_name",
                label_visibility="collapsed",
                placeholder="Name this prompt to save...",
            )
        with sa_btn:
            if st.button("Save", use_container_width=True, key="_btn_save_new",
                         disabled=not save_name.strip(), type="primary"):
                save_enrichment_prompt(save_name.strip(), current_text)
                st.session_state["_loaded_prompt_name"] = save_name.strip()
                st.session_state["_loaded_prompt_text"] = current_text
                st.rerun()

    elif saveas_mode:
        # Save as new → name input row
        sa_col, sa_btn, cancel_col = st.columns([4, 1, 1])
        with sa_col:
            saveas_name = st.text_input(
                "New name", key="_saveas_name_input",
                label_visibility="collapsed",
                placeholder="New prompt name...",
            )
        with sa_btn:
            if st.button("Save", use_container_width=True, key="_btn_saveas_confirm",
                         disabled=not saveas_name.strip(), type="primary"):
                save_enrichment_prompt(saveas_name.strip(), current_text)
                st.session_state["_loaded_prompt_name"] = saveas_name.strip()
                st.session_state["_loaded_prompt_text"] = current_text
                st.session_state["_saveas_mode"] = False
                st.rerun()
        with cancel_col:
            if st.button("Cancel", use_container_width=True, key="_btn_saveas_cancel"):
                st.session_state["_saveas_mode"] = False
                st.rerun()

    elif is_dirty:
        # Dirty existing prompt → Update + Save as new + Del
        upd_col, saveas_col, del_col = st.columns([2, 2, 1])
        with upd_col:
            if st.button("Update *", use_container_width=True, key="_btn_update", type="primary"):
                save_enrichment_prompt(loaded_name, current_text)
                st.session_state["_loaded_prompt_text"] = current_text
                st.rerun()
        with saveas_col:
            if st.button("Save as new", use_container_width=True, key="_btn_saveas"):
                st.session_state["_saveas_mode"] = True
                st.rerun()
        with del_col:
            _render_delete_btn(loaded_name)

    else:
        # Clean loaded prompt → just Delete (small, unobtrusive)
        _, del_col = st.columns([8, 1])
        with del_col:
            _render_delete_btn(loaded_name)


def render_prompt_editor(df: pd.DataFrame | None = None) -> str:
    """Renders prompt library + side-by-side editor. Returns prompt_text."""

    if "prompt_textarea" not in st.session_state:
        st.session_state.prompt_textarea = _DEFAULT_TEXT

    _render_prompt_library()

    col_edit, col_preview = st.columns([1, 1], gap="small")

    with col_edit:
        st.text_area(
            "prompt",
            height=340,
            key="prompt_textarea",
            label_visibility="collapsed",
            placeholder="Write your question here. Use {{Column Name}} to insert data.",
        )

    with col_preview:
        current_text = st.session_state.get("prompt_textarea", "")
        found_cols = re.findall(r"\{\{(.+?)\}\}", current_text)

        if df is not None and not df.empty:
            if st.button("Next sample", key="_btn_next_sample", use_container_width=False):
                cur_idx = st.session_state.get("_preview_idx", 0)
                candidates = [
                    i for i in range(len(df))
                    if i != cur_idx and not _is_empty_row(df.iloc[i])
                ]
                if candidates:
                    st.session_state["_preview_idx"] = random.choice(candidates)
                st.rerun()

            preview_idx = st.session_state.get("_preview_idx")
            if preview_idx is not None and preview_idx < len(df) and not _is_empty_row(df.iloc[preview_idx]):
                preview_row = df.iloc[preview_idx]
            else:
                preview_row = _find_preview_row(df, found_cols)

            rendered = render_prompt_preview(current_text, df, preview_row)
            st.code(rendered, language=None)

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

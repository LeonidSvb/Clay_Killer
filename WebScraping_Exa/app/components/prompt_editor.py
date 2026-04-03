"""
app/components/prompt_editor.py — Side-by-side prompt editor with live preview + prompt library.

Layout:
  [ Select saved prompt ▼ ] [+ New]   name: [editable]   [Update] [Delete]
  ┌──────────────────────┬─────────────────────────────────────────┐
  │ textarea (editable)  │ Output type: [Text ▼]  [config fields]  │
  │                      │ [Next sample]                           │
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

OUTPUT_TYPES = ["Text", "Boolean", "Score", "Structured"]

_DEFAULT_TEXT = "Is {{Company Name}} a [YOUR CRITERIA]?"
_DEFAULT_OUTPUT_TYPE = "Text"


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


def _render_prompt_library() -> None:
    """Prompt library: load, save, rename, delete saved prompts."""
    saved = list_enrichment_prompts()

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
            text, _, default_output_col, loaded_ot, loaded_oc = load_enrichment_prompt(selected)
            st.session_state.prompt_textarea = text
            st.session_state["_loaded_prompt_name"] = selected
            st.session_state["_loaded_prompt_text"] = text
            st.session_state["prompt_default_output_col"] = default_output_col
            st.session_state["panel_output_type"] = loaded_ot or _DEFAULT_OUTPUT_TYPE
            st.session_state["panel_output_config"] = loaded_oc or {}
            st.session_state["_loaded_output_type"] = loaded_ot or _DEFAULT_OUTPUT_TYPE
            st.session_state["_loaded_output_config"] = loaded_oc or {}
            st.session_state.pop("_confirm_delete", None)
            st.rerun()

    with new_col:
        if st.button("+ New", use_container_width=True, key="_btn_new_prompt"):
            st.session_state.prompt_textarea = _DEFAULT_TEXT
            st.session_state["_loaded_prompt_name"] = ""
            st.session_state["_loaded_prompt_text"] = ""
            st.session_state.pop("_confirm_delete", None)
            st.rerun()

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
                "Update" + (" *" if is_modified else ""),
                use_container_width=True,
                key="_btn_update",
                type="primary" if is_modified else "secondary",
                disabled=not is_modified,
            ):
                clean_name = new_name.strip()
                if clean_name and clean_name != loaded_name:
                    delete_enrichment_prompt(loaded_name)
                output_type = st.session_state.get("panel_output_type", _DEFAULT_OUTPUT_TYPE)
                output_config = st.session_state.get("panel_output_config", {})
                save_enrichment_prompt(clean_name or loaded_name, current_text, output_type, output_config)
                st.session_state["_loaded_prompt_name"] = clean_name or loaded_name
                st.session_state["_loaded_prompt_text"] = current_text
                st.session_state["_loaded_output_type"] = output_type
                st.session_state["_loaded_output_config"] = output_config
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
                output_type = st.session_state.get("panel_output_type", _DEFAULT_OUTPUT_TYPE)
                output_config = st.session_state.get("panel_output_config", {})
                save_enrichment_prompt(save_name.strip(), current_text, output_type, output_config)
                st.session_state["_loaded_prompt_name"] = save_name.strip()
                st.session_state["_loaded_prompt_text"] = current_text
                st.session_state["_loaded_output_type"] = output_type
                st.session_state["_loaded_output_config"] = output_config
                st.rerun()
    else:
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
                output_type = st.session_state.get("panel_output_type", _DEFAULT_OUTPUT_TYPE)
                output_config = st.session_state.get("panel_output_config", {})
                save_enrichment_prompt(save_name.strip(), current_text, output_type, output_config)
                st.session_state["_loaded_prompt_name"] = save_name.strip()
                st.session_state["_loaded_prompt_text"] = current_text
                st.session_state["_loaded_output_type"] = output_type
                st.session_state["_loaded_output_config"] = output_config
                st.rerun()


def _render_output_config(output_type: str) -> dict:
    """Render output config widgets for the given type. Returns the current config dict."""
    cfg = dict(st.session_state.get("panel_output_config") or {})

    if output_type == "Boolean":
        cfg["confidence"] = st.checkbox(
            "Include confidence",
            value=cfg.get("confidence", True),
            key="_oc_bool_confidence",
        )

    elif output_type == "Score":
        c1, c2 = st.columns(2)
        with c1:
            scale = st.selectbox(
                "Scale",
                ["0-10", "0-100"],
                index=0 if cfg.get("scale", "0-10") == "0-10" else 1,
                key="_oc_score_scale",
                label_visibility="collapsed",
            )
            cfg["scale"] = scale
        with c2:
            cfg["confidence"] = st.checkbox(
                "Confidence",
                value=cfg.get("confidence", True),
                key="_oc_score_confidence",
            )

    elif output_type == "Structured":
        schema_val = cfg.get("schema", '{\n  "field": "string"\n}')
        new_schema = st.text_area(
            "JSON schema",
            value=schema_val,
            height=80,
            key="_oc_structured_schema",
            label_visibility="collapsed",
            placeholder='{"field": "string", "tags": ["string"]}',
        )
        cfg["schema"] = new_schema

    return cfg


def render_prompt_editor(df: pd.DataFrame | None = None) -> tuple[str, str, dict]:
    """Renders prompt library + side-by-side editor. Returns (prompt_text, output_type, output_config)."""

    if "prompt_textarea" not in st.session_state:
        backup = st.session_state.get("_prompt_backup", _DEFAULT_TEXT)
        st.session_state.prompt_textarea = backup

    _render_prompt_library()

    col_edit, col_preview = st.columns([1, 1], gap="small")

    with col_edit:
        st.text_area(
            "prompt",
            height=220,
            key="prompt_textarea",
            label_visibility="collapsed",
            placeholder="Write your question here. Use {{Column Name}} to insert data.",
        )

    with col_preview:
        # Output type selector
        ot_col, _ = st.columns([3, 1])
        with ot_col:
            output_type = st.selectbox(
                "Output type",
                OUTPUT_TYPES,
                index=OUTPUT_TYPES.index(
                    st.session_state.get("panel_output_type", _DEFAULT_OUTPUT_TYPE)
                ) if st.session_state.get("panel_output_type", _DEFAULT_OUTPUT_TYPE) in OUTPUT_TYPES else 0,
                key="panel_output_type",
                label_visibility="collapsed",
            )

        output_config = _render_output_config(output_type)

        # Auto-save output config when it changes (if a prompt is loaded)
        loaded_name = st.session_state.get("_loaded_prompt_name", "")
        if loaded_name:
            prev_ot = st.session_state.get("_loaded_output_type", "")
            prev_oc = st.session_state.get("_loaded_output_config", {})
            if output_type != prev_ot or output_config != prev_oc:
                current_text = st.session_state.get("prompt_textarea", "")
                save_enrichment_prompt(loaded_name, current_text, output_type, output_config)
                st.session_state["_loaded_output_type"] = output_type
                st.session_state["_loaded_output_config"] = output_config

        st.session_state["panel_output_config"] = output_config

        # Next sample button + preview
        current_text = st.session_state.get("prompt_textarea", "")
        found_cols = re.findall(r"\{\{(.+?)\}\}", current_text)

        if df is not None and not df.empty:
            # Next sample button
            if st.button("Next sample", key="_btn_next_sample", use_container_width=False):
                # Pick a random non-empty row, different from current preview_idx
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

    return current_text, output_type, output_config

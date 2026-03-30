"""
TASK-006b automated tests: prompt editor + LLM enrichment adapter.
Run: py -m pytest tests/test_006b.py -v
"""

import inspect
import queue
import threading

import pandas as pd
import pytest


# ── prompt_editor helpers ──────────────────────────────────────────────────────

def test_render_prompt_preview_basic():
    from app.enrichments.llm import render_prompt_preview
    df = pd.DataFrame([{"Company Name": "Acme Corp", "Website": "acme.com"}])
    template = "Company: {{Company Name}}, site: {{Website}}"
    result = render_prompt_preview(template, df)
    assert result == "Company: Acme Corp, site: acme.com"


def test_render_prompt_preview_missing_column():
    from app.enrichments.llm import render_prompt_preview
    df = pd.DataFrame([{"Company Name": "Acme Corp"}])
    template = "Company: {{Company Name}}, site: {{Website}}"
    result = render_prompt_preview(template, df)
    # {{Website}} is not replaced (column not in df)
    assert "Acme Corp" in result
    assert "{{Website}}" in result


def test_render_prompt_preview_empty_df():
    from app.enrichments.llm import render_prompt_preview
    template = "Company: {{Company Name}}"
    result = render_prompt_preview(template, None)
    assert result == template


def test_render_prompt_preview_nan_value():
    from app.enrichments.llm import render_prompt_preview
    df = pd.DataFrame([{"Company Name": "nan", "Website": "acme.com"}])
    template = "Company: {{Company Name}}"
    result = render_prompt_preview(template, df)
    assert result == "Company: "


# ── llm adapter interface ──────────────────────────────────────────────────────

def test_run_llm_enrichment_signature():
    from app.enrichments.llm import run_llm_enrichment
    params = inspect.signature(run_llm_enrichment).parameters
    required = ["df", "input_columns", "prompt_name", "row_indices",
                "concurrency", "progress_queue", "stop_event"]
    for name in required:
        assert name in params, f"Missing parameter: {name}"


def test_render_prompt_for_row_column_style():
    from app.enrichments.llm import render_prompt_for_row
    df = pd.DataFrame([{"Company": "Acme", "Revenue": "5M"}])
    row = df.iloc[0]
    template = "Co: {{Company}}, Rev: {{Revenue}}"
    result = render_prompt_for_row(template, row, ["Company", "Revenue"], is_column_style=True)
    assert result == "Co: Acme, Rev: 5M"


def test_render_prompt_for_row_legacy_style():
    from app.enrichments.llm import render_prompt_for_row
    df = pd.DataFrame([{"Website Summary": "Logistics company"}])
    row = df.iloc[0]
    template = "Analyze: {text}"
    result = render_prompt_for_row(template, row, ["Website Summary"], is_column_style=False)
    assert "Logistics company" in result
    assert "{text}" not in result


def test_render_prompt_for_row_skips_nan():
    from app.enrichments.llm import render_prompt_for_row
    df = pd.DataFrame([{"Company": "nan", "Website": "acme.com"}])
    row = df.iloc[0]
    template = "{text}"
    result = render_prompt_for_row(template, row, ["Company", "Website"], is_column_style=False)
    assert "nan" not in result
    assert "acme.com" in result


# ── prompt file helpers ────────────────────────────────────────────────────────

def test_list_enrichment_prompts_returns_list():
    from app.enrichments.llm import list_enrichment_prompts
    prompts = list_enrichment_prompts()
    assert isinstance(prompts, list)
    assert len(prompts) > 0


def test_list_enrichment_prompts_no_system_context():
    from app.enrichments.llm import list_enrichment_prompts
    prompts = list_enrichment_prompts()
    assert "system_context" not in prompts


def test_load_enrichment_prompt_existing():
    from app.enrichments.llm import load_enrichment_prompt
    template, is_col = load_enrichment_prompt("company_full")
    assert isinstance(template, str)
    assert len(template) > 10
    assert isinstance(is_col, bool)


def test_load_enrichment_prompt_missing():
    from app.enrichments.llm import load_enrichment_prompt
    with pytest.raises(FileNotFoundError):
        load_enrichment_prompt("__nonexistent_prompt_xyz__")


def test_save_and_delete_enrichment_prompt(tmp_path, monkeypatch):
    import app.enrichments.llm as llm_mod
    monkeypatch.setattr(llm_mod, "ENRICHMENT_PROMPTS_DIR", tmp_path)

    from app.enrichments.llm import save_enrichment_prompt, delete_enrichment_prompt, load_enrichment_prompt

    save_enrichment_prompt("test_prompt", "Hello {{Company Name}}")
    template, is_col = load_enrichment_prompt("test_prompt")
    assert "Hello" in template
    assert is_col is True

    deleted = delete_enrichment_prompt("test_prompt")
    assert deleted is True

    deleted_again = delete_enrichment_prompt("test_prompt")
    assert deleted_again is False

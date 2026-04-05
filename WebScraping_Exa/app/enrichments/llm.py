"""
app/enrichments/llm.py — LLM enrichment adapter for Streamlit.

Wraps core/llm.py async logic in threading.Thread + queue.Queue.
All prompts stored in prompts.json (project root) via core.prompts_store.
"""

import asyncio
import os
import queue
import threading
import time

import httpx
import pandas as pd

from core.llm import parse_json_response, load_system_context
from core.errors import normalize_http_error, normalize_exception
from core import prompts_store

DEFAULT_MODEL = "openai/gpt-oss-120b"

LLM_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "google/gemini-2.0-flash-001",
    "google/gemini-2.5-pro-preview-03-25",
    "anthropic/claude-haiku-4-5",
    "anthropic/claude-sonnet-4-5",
    "deepseek/deepseek-chat",
    "meta-llama/llama-3.3-70b-instruct",
]


# ── Prompt helpers ─────────────────────────────────────────────────────────────

def list_enrichment_prompts() -> list[str]:
    return prompts_store.list_prompts()


def load_enrichment_prompt(name: str) -> tuple[str, bool, str, str, dict]:
    """Returns (template_text, is_column_style, default_output_col, output_type, output_config)."""
    entry = prompts_store.get_prompt(name)
    template = entry.get("prompt", "")
    output_type = entry.get("output_type", "Text")
    output_config = entry.get("output_config", {})
    is_column_style = "{text}" not in template
    return template, is_column_style, "", output_type, output_config


def save_enrichment_prompt(
    name: str,
    content: str,
    output_type: str = "Text",
    output_config: dict | None = None,
) -> None:
    prompts_store.set_prompt(name, content, output_type or "Text", output_config)


def delete_enrichment_prompt(name: str) -> bool:
    return prompts_store.delete_prompt(name)


# ── JSON output suffixes by type ───────────────────────────────────────────────

JSON_SUFFIXES: dict[str, str] = {
    "Boolean": (
        '\n\nReturn JSON only: '
        '{"result": true, "confidence": <1-10 based on info quality>, "reasoning": "one sentence"}'
    ),
    "Score 0-10": (
        '\n\nReturn JSON only: '
        '{"score": <0-10>, "confidence": <1-10 based on info quality>, "reasoning": "one sentence"}'
    ),
    "Extract": (
        '\n\nReturn JSON only: '
        '{"value": "extracted text", "confidence": <1-10 based on info quality>}'
    ),
    "Full profile": (
        '\n\nReturn JSON only: '
        '{"summary": "2-3 sentences", "industry": "primary industry", '
        '"target_market": "who they sell to", "confidence": <1-10 based on info quality>}'
    ),
}


# ── Row rendering ──────────────────────────────────────────────────────────────

_EXTRACT_WITH_REASONING = (
    '\n\nReturn JSON only: '
    '{"value": "extracted text", "confidence": <1-10 based on info quality>, "reasoning": "one sentence"}'
)


_GUARDRAIL = (
    '\n\nIf you cannot determine this from the available information, '
    'use "INSUFFICIENT_DATA" as the main value and set confidence to 1.'
)


def get_json_suffix(
    output_type: str,
    include_reasoning: bool = False,
    include_guardrail: bool = False,
) -> str:
    if output_type == "Extract" and include_reasoning:
        base = _EXTRACT_WITH_REASONING
    else:
        base = JSON_SUFFIXES.get(output_type, JSON_SUFFIXES["Extract"])
    if include_guardrail:
        base += _GUARDRAIL
    return base


def get_json_suffix_v2(output_type: str, output_config: dict | None = None) -> str:
    """New-style suffix generator using output_config dict."""
    cfg = output_config or {}
    if output_type == "Text":
        return '\n\nReturn JSON only: {"value": "your answer here"}'
    elif output_type == "Boolean":
        if cfg.get("confidence", True):
            return '\n\nReturn JSON only: {"result": true, "confidence": <1-10 based on available data>}'
        return '\n\nReturn JSON only: {"result": true}'
    elif output_type == "Score":
        scale = cfg.get("scale", "0-10")
        if cfg.get("confidence", True):
            return f'\n\nReturn JSON only: {{"score": <{scale}>, "confidence": <1-10 based on available data>}}'
        return f'\n\nReturn JSON only: {{"score": <{scale}>}}'
    elif output_type == "Structured":
        schema = cfg.get("schema", '{"value": "string"}').strip()
        return f'\n\nReturn JSON only: {schema}'
    # Legacy fallback
    return get_json_suffix(output_type)


def render_prompt_for_row(
    template: str,
    row: pd.Series,
    # legacy params kept for backward compat — no longer appended automatically
    output_type: str = "Text",
    output_config: dict | None = None,
    include_reasoning: bool = False,
    include_guardrail: bool = False,
) -> str:
    filled = template
    for col in row.index:
        val = str(row.get(col, "")).strip()
        if val in ("nan", "None"):
            val = ""
        filled = filled.replace("{{" + col + "}}", val)
    return filled


def render_prompt_preview(
    template: str,
    df: pd.DataFrame,
    row: pd.Series | None = None,
) -> str:
    """Fill template with values from given row (defaults to first row)."""
    if df is None or df.empty:
        return template
    if row is None:
        row = df.iloc[0]
    filled = template
    for col in df.columns:
        val = str(row.get(col, "")).strip()
        if val in ("nan", "None"):
            val = ""
        filled = filled.replace("{{" + col + "}}", val)
    return filled


# ── Async LLM caller ───────────────────────────────────────────────────────────

async def _call_llm_batch(
    items: list[dict],
    concurrency: int,
    api_key: str,
    progress_queue: queue.Queue,
    stop_event: threading.Event,
    model: str = DEFAULT_MODEL,
    result_queue: queue.Queue | None = None,
) -> list[dict]:
    """
    items: [{"idx": int, "rendered_prompt": str}, ...]
    Returns: [{"idx": int, "data": dict, "ok": bool, "error": str|None}, ...]
    """
    system = load_system_context()
    sem = asyncio.Semaphore(concurrency)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    results: list[dict] = []
    total = len(items)
    t0 = time.time()

    async def call_one(item: dict) -> dict:
        idx = item["idx"]
        rendered = item["rendered_prompt"]
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": rendered},
            ],
            "temperature": 0.1,
            "provider": {"sort": "throughput"},
        }
        async with sem:
            if stop_event.is_set():
                return {"idx": idx, "data": {}, "ok": False, "error": "stopped", "elapsed": 0.0}
            t_row = time.time()
            try:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json=payload,
                    timeout=30.0,
                )
                elapsed_row = time.time() - t_row
                if resp.status_code != 200:
                    return {"idx": idx, "data": {}, "ok": False,
                            "error": normalize_http_error(resp.status_code, resp.text),
                            "elapsed": elapsed_row}
                data = resp.json()
                raw_content = data["choices"][0]["message"]["content"]
                if not raw_content:
                    return {"idx": idx, "data": {}, "ok": False, "error": "llm_empty_response",
                            "elapsed": elapsed_row}
                parsed = parse_json_response(raw_content)
                if not parsed:
                    return {"idx": idx, "data": {}, "ok": False, "error": "llm_parse_error",
                            "elapsed": elapsed_row}
                return {"idx": idx, "data": parsed, "ok": True, "error": None, "elapsed": elapsed_row}
            except Exception as exc:
                return {"idx": idx, "data": {}, "ok": False,
                        "error": normalize_exception(exc),
                        "elapsed": time.time() - t_row}

    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [asyncio.create_task(call_one(item)) for item in items]
        for coro in asyncio.as_completed(tasks):
            if stop_event.is_set():
                for t in tasks:
                    t.cancel()
                break
            result = await coro
            results.append(result)
            if result_queue is not None:
                result_queue.put_nowait(result)
            done = len(results)
            elapsed = time.time() - t0
            speed = done / elapsed if elapsed > 0 else 0
            eta = int((total - done) / speed) if speed > 0 and done < total else 0
            ok = sum(1 for r in results if r["ok"])
            progress_queue.put_nowait({
                "done": done,
                "total": total,
                "ok": ok,
                "errors": done - ok,
                "speed": speed,
                "eta": eta,
            })

    return results


# ── Public entry point ─────────────────────────────────────────────────────────

def run_llm_enrichment(
    df: pd.DataFrame,
    prompt_text: str,
    row_indices: list[int],
    concurrency: int,
    progress_queue: queue.Queue,
    stop_event: threading.Event,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    result_queue: queue.Queue | None = None,
    # legacy params — accepted but ignored
    output_type: str = "Text",
    output_config: dict | None = None,
    include_reasoning: bool = False,
    include_guardrail: bool = False,
) -> list[dict]:
    """
    Runs LLM enrichment synchronously (call inside threading.Thread).
    Returns list of {"idx": int, "data": dict, "ok": bool, "error": str|None, "elapsed": float}.
    """
    key = api_key or os.getenv("OPENROUTER_API_KEY", "")

    items = []
    for idx in row_indices:
        row = df.iloc[idx]
        rendered = render_prompt_for_row(prompt_text, row)
        items.append({"idx": idx, "rendered_prompt": rendered})

    return asyncio.run(_call_llm_batch(
        items=items,
        concurrency=concurrency,
        api_key=key,
        progress_queue=progress_queue,
        stop_event=stop_event,
        model=model,
        result_queue=result_queue,
    ))

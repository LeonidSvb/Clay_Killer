"""
app/enrichments/llm.py — LLM enrichment adapter for Streamlit.

Wraps core/llm.py async logic in threading.Thread + queue.Queue.
Supports two prompt modes:
  - prompts/enrichment/*.txt  → {{column_name}} substitution per row
  - prompts/*.txt             → concatenate input_columns as {text} substitution
"""

import asyncio
import os
import queue
import threading
import time
from pathlib import Path

import httpx
import pandas as pd

from core.llm import parse_json_response, load_system_context

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
ENRICHMENT_PROMPTS_DIR = PROMPTS_DIR / "enrichment"
DEFAULT_MODEL = "openai/gpt-oss-120b"


# ── Prompt helpers ─────────────────────────────────────────────────────────────

def list_enrichment_prompts() -> list[str]:
    names: set[str] = set()
    if ENRICHMENT_PROMPTS_DIR.exists():
        for p in ENRICHMENT_PROMPTS_DIR.glob("*.txt"):
            names.add(p.stem)
    for p in PROMPTS_DIR.glob("*.txt"):
        if p.stem != "system_context":
            names.add(p.stem)
    return sorted(names)


def load_enrichment_prompt(name: str) -> tuple[str, bool]:
    """
    Returns (template_text, is_column_style).
    is_column_style=True → use {{col}} substitution.
    is_column_style=False → use {text} substitution (legacy CLI prompts).
    """
    enrichment_path = ENRICHMENT_PROMPTS_DIR / f"{name}.txt"
    if enrichment_path.exists():
        return enrichment_path.read_text(encoding="utf-8"), True

    root_path = PROMPTS_DIR / f"{name}.txt"
    if root_path.exists():
        return root_path.read_text(encoding="utf-8"), False

    raise FileNotFoundError(f"Prompt not found: {name}")


def save_enrichment_prompt(name: str, content: str) -> None:
    ENRICHMENT_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    (ENRICHMENT_PROMPTS_DIR / f"{name}.txt").write_text(content, encoding="utf-8")


def delete_enrichment_prompt(name: str) -> bool:
    path = ENRICHMENT_PROMPTS_DIR / f"{name}.txt"
    if path.exists():
        path.unlink()
        return True
    return False


# ── Row rendering ──────────────────────────────────────────────────────────────

def render_prompt_for_row(
    template: str,
    row: pd.Series,
    input_columns: list[str],
    is_column_style: bool,
) -> str:
    if is_column_style:
        filled = template
        for col in row.index:
            val = str(row.get(col, "")).strip()
            if val in ("nan", "None"):
                val = ""
            filled = filled.replace("{{" + col + "}}", val)
        return filled
    else:
        # Legacy: concatenate input_columns as text
        parts = []
        for col in input_columns:
            val = str(row.get(col, "")).strip()
            if val and val not in ("nan", "None"):
                parts.append(f"{col}: {val}")
        text = "\n".join(parts)
        try:
            return template.format(text=text)
        except KeyError:
            return template


def render_prompt_preview(template: str, df: pd.DataFrame) -> str:
    """Fill template with values from first row — for prompt editor preview."""
    if df is None or df.empty:
        return template
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
            "model": DEFAULT_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": rendered},
            ],
            "temperature": 0.1,
            "provider": {"sort": "throughput"},
        }
        async with sem:
            if stop_event.is_set():
                return {"idx": idx, "data": {}, "ok": False, "error": "stopped"}
            try:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json=payload,
                    timeout=90.0,
                )
                if resp.status_code != 200:
                    return {"idx": idx, "data": {}, "ok": False,
                            "error": f"HTTP {resp.status_code}: {resp.text[:80]}"}
                data = resp.json()
                raw_content = data["choices"][0]["message"]["content"]
                if not raw_content:
                    return {"idx": idx, "data": {}, "ok": False, "error": "empty_response"}
                parsed = parse_json_response(raw_content)
                return {"idx": idx, "data": parsed, "ok": True, "error": None}
            except Exception as exc:
                return {"idx": idx, "data": {}, "ok": False, "error": str(exc)[:120]}

    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [asyncio.create_task(call_one(item)) for item in items]
        for coro in asyncio.as_completed(tasks):
            if stop_event.is_set():
                for t in tasks:
                    t.cancel()
                break
            result = await coro
            results.append(result)
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
    input_columns: list[str],
    prompt_name: str,
    row_indices: list[int],
    concurrency: int,
    progress_queue: queue.Queue,
    stop_event: threading.Event,
    api_key: str = "",
) -> list[dict]:
    """
    Runs LLM enrichment synchronously (call inside threading.Thread).
    Returns list of {"idx": int, "data": dict, "ok": bool, "error": str|None}.
    """
    template, is_column_style = load_enrichment_prompt(prompt_name)
    key = api_key or os.getenv("OPENROUTER_API_KEY", "")

    items = []
    for idx in row_indices:
        row = df.iloc[idx]
        rendered = render_prompt_for_row(template, row, input_columns, is_column_style)
        items.append({"idx": idx, "rendered_prompt": rendered})

    return asyncio.run(_call_llm_batch(
        items=items,
        concurrency=concurrency,
        api_key=key,
        progress_queue=progress_queue,
        stop_event=stop_event,
    ))

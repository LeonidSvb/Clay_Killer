"""
app/enrichments/llm.py — LLM enrichment adapter for Streamlit.

Wraps core/llm.py async logic in threading.Thread + queue.Queue.

Prompt locations:
  - prompts/enrichment/  → Streamlit enrichment prompts (shown in panel)
  - prompts/             → CLI-only prompts (not shown in panel)

Prompt style detection (by content, not path):
  - has {{col}} and no {text}  → column style: replace {{col}} per row
  - has {text}                 → legacy style: concatenate input_columns → format(text=)
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
    """Only returns prompts from prompts/enrichment/ — panel-specific."""
    if not ENRICHMENT_PROMPTS_DIR.exists():
        return []
    return sorted(p.stem for p in ENRICHMENT_PROMPTS_DIR.glob("*.txt"))


def load_enrichment_prompt(name: str) -> tuple[str, bool, str]:
    """
    Returns (template_text, is_column_style, default_output_col).
    Detection is content-based:
      - has {text}            → legacy style: concatenate input_columns → format(text=)
      - no {text}, has {{..}} → column style: replace {{col}} per row
      - neither               → legacy style (concatenate as fallback)
    Parses `# output: ColName` lines from template and strips them before returning.
    """
    path = ENRICHMENT_PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found in prompts/enrichment/: {name}")
    raw = path.read_text(encoding="utf-8")

    # Parse and strip `# output: ColName` metadata lines
    output_col = ""
    clean_lines = []
    for line in raw.splitlines():
        if line.startswith("# output:"):
            output_col = line[len("# output:"):].strip()
        else:
            clean_lines.append(line)
    template = "\n".join(clean_lines).rstrip("\n") + "\n"

    is_column_style = "{text}" not in template
    return template, is_column_style, output_col


def save_enrichment_prompt(name: str, content: str) -> None:
    ENRICHMENT_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    (ENRICHMENT_PROMPTS_DIR / f"{name}.txt").write_text(content, encoding="utf-8")


def delete_enrichment_prompt(name: str) -> bool:
    path = ENRICHMENT_PROMPTS_DIR / f"{name}.txt"
    if path.exists():
        path.unlink()
        return True
    return False


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


def render_prompt_for_row(
    template: str,
    row: pd.Series,
    output_type: str = "Extract",
    include_reasoning: bool = False,
    include_guardrail: bool = False,
) -> str:
    filled = template
    for col in row.index:
        val = str(row.get(col, "")).strip()
        if val in ("nan", "None"):
            val = ""
        filled = filled.replace("{{" + col + "}}", val)
    filled += get_json_suffix(output_type, include_reasoning, include_guardrail)
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
                            "error": f"HTTP {resp.status_code}: {resp.text[:80]}",
                            "elapsed": elapsed_row}
                data = resp.json()
                raw_content = data["choices"][0]["message"]["content"]
                if not raw_content:
                    return {"idx": idx, "data": {}, "ok": False, "error": "empty_response",
                            "elapsed": elapsed_row}
                parsed = parse_json_response(raw_content)
                return {"idx": idx, "data": parsed, "ok": True, "error": None, "elapsed": elapsed_row}
            except Exception as exc:
                return {"idx": idx, "data": {}, "ok": False, "error": str(exc)[:120],
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
    output_type: str = "Extract",
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
        rendered = render_prompt_for_row(prompt_text, row, output_type, include_reasoning, include_guardrail)
        items.append({"idx": idx, "rendered_prompt": rendered})

    return asyncio.run(_call_llm_batch(
        items=items,
        concurrency=concurrency,
        api_key=key,
        progress_queue=progress_queue,
        stop_event=stop_event,
    ))

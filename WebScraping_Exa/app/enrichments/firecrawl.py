"""
app/enrichments/firecrawl.py — Firecrawl enrichment adapter.

Formats (combinable, sent in one API call):
  markdown  — raw scraped markdown text       → fc_markdown
  json      — structured JSON extraction      → one col per schema key  OR  fc_json (single col)

Extract modes (when "json" format is selected):
  firecrawl — Firecrawl built-in LLM extraction (5 credits/call, high quality)
  llm       — Firecrawl markdown (1 credit) + OpenRouter LLM (cheap, model of choice)

Key rotation: round-robin across FIRECRAWL_KEY_1/2/3 (.env), 2 req/sec per key.

cfg keys:
  formats           list[str]   — subset of ["markdown", "json"]
  json_prompt       str         — natural language extraction instruction
  json_schema       dict        — JSON Schema object (properties at top level)
  json_split        bool        — True = one col per key, False = fc_json single col
  only_main_content bool        — strip nav/footer (default False for contact extraction)
  llm_extract       bool        — True = use LLM instead of Firecrawl extraction
  llm_model         str         — OpenRouter model id (used when llm_extract=True)
  openrouter_key    str         — OpenRouter API key (used when llm_extract=True)
"""

import asyncio
import itertools
import json
import os
import queue
import threading
import time
from typing import Any

import aiohttp
import pandas as pd

from core.errors import (
    error_result, success_result,
    normalize_http_error, normalize_exception,
)
from core.llm import parse_json_response

FC_BASE = "https://api.firecrawl.dev/v1"
RATE_PER_KEY = 2.0

DEFAULT_JSON_PROMPT = (
    "Extract all contact information from this page: "
    "email addresses, phone numbers, postal code, contact person names, "
    "physical address, and company name."
)

DEFAULT_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "emails":        {"type": "array", "items": {"type": "string"}},
        "phones":        {"type": "array", "items": {"type": "string"}},
        "postal_code":   {"type": "string"},
        "contact_names": {"type": "array", "items": {"type": "string"}},
        "address":       {"type": "string"},
        "company_name":  {"type": "string"},
    },
}

LLM_EXTRACT_SYSTEM = (
    "You are a structured data extraction assistant. "
    "Extract information from the provided webpage content and return ONLY a valid JSON object. "
    "No markdown fences, no explanation — just the JSON."
)

LLM_MARKDOWN_LIMIT = 12000


# ── Key pool ───────────────────────────────────────────────────────────────────

def _load_keys() -> list[str]:
    keys = []
    for i in range(1, 6):
        k = os.getenv(f"FIRECRAWL_KEY_{i}", "")
        if k:
            keys.append(k)
    if not keys:
        legacy = os.getenv("FIRECRAWL_API_KEY", "")
        if legacy:
            keys.append(legacy)
    return keys


class _KeyPool:
    def __init__(self, keys: list[str], rate: float = RATE_PER_KEY):
        self._keys = keys
        self._rate = rate
        self._cycle = itertools.cycle(range(len(keys)))
        self._last = [0.0] * len(keys)
        self._locks = [asyncio.Lock() for _ in keys]

    async def acquire(self) -> str:
        idx = next(self._cycle)
        async with self._locks[idx]:
            wait = self._last[idx] + 1.0 / self._rate - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[idx] = time.monotonic()
        return self._keys[idx]


# ── Payload builder ────────────────────────────────────────────────────────────

def _build_payload(url: str, cfg: dict) -> dict:
    formats = cfg.get("formats", ["markdown"])
    payload: dict[str, Any] = {
        "url": url,
        "onlyMainContent": cfg.get("only_main_content", False),
        "timeout": 30000,
    }

    api_formats = []
    if "markdown" in formats:
        api_formats.append("markdown")
    # When llm_extract=True we only need markdown — skip Firecrawl's own extraction
    if "json" in formats and not cfg.get("llm_extract"):
        api_formats.append("extract")
        payload["extract"] = {
            "prompt": cfg.get("json_prompt", DEFAULT_JSON_PROMPT),
            "schema": cfg.get("json_schema", DEFAULT_JSON_SCHEMA),
        }

    # LLM extract mode always needs markdown
    if cfg.get("llm_extract") and "markdown" not in api_formats:
        api_formats.append("markdown")

    payload["formats"] = api_formats
    return payload


# ── Output extractor ───────────────────────────────────────────────────────────

def _apply_split(extracted: dict, split: bool) -> dict:
    """Convert an extracted dict to split columns or single fc_json column."""
    out: dict = {}
    if split:
        for k, v in extracted.items():
            if v is None:
                continue
            if isinstance(v, list):
                out[k] = ", ".join(str(i) for i in v if i is not None and str(i).strip())
            elif isinstance(v, dict):
                out[k] = json.dumps(v, ensure_ascii=False)
            else:
                out[k] = v
    else:
        out["fc_json"] = json.dumps(extracted, ensure_ascii=False)
    return out


def _extract_output(data: dict, cfg: dict) -> dict:
    formats = cfg.get("formats", ["markdown"])
    split   = cfg.get("json_split", True)
    out: dict = {}

    if "markdown" in formats:
        md = data.get("markdown") or ""
        if md:
            out["fc_markdown"] = md

    if "json" in formats and not cfg.get("llm_extract"):
        extracted = data.get("extract") or {}
        if extracted:
            out.update(_apply_split(extracted, split))

    return out


# ── LLM extraction (markdown → OpenRouter) ─────────────────────────────────────

async def _llm_extract(
    markdown: str,
    prompt: str,
    schema: dict,
    model: str,
    api_key: str,
    session: aiohttp.ClientSession,
) -> dict:
    """Send markdown to OpenRouter LLM, return extracted dict matching schema."""
    schema_str = json.dumps(schema, ensure_ascii=False)
    user_msg = (
        f"{prompt}\n\n"
        f"Return a JSON object matching this schema:\n{schema_str}\n\n"
        f"Webpage content:\n{markdown[:LLM_MARKDOWN_LIMIT]}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": LLM_EXTRACT_SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        "temperature": 0,
        "provider": {"sort": "throughput"},
    }
    try:
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json()
            content = data["choices"][0]["message"]["content"]
            return parse_json_response(content) or {}
    except Exception:
        return {}


# ── Async fetcher ──────────────────────────────────────────────────────────────

async def _fetch_one(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    pool: _KeyPool,
    item: dict,
    cfg: dict,
    stop_event: threading.Event,
) -> dict:
    idx = item["idx"]
    url = item["url"]

    if stop_event.is_set():
        return error_result(idx, "sys_stopped", url=url)

    if not url or url in ("nan", "None", "http://", "https://"):
        return error_result(idx, "data_empty_url", url=url)

    t0 = time.time()
    async with sem:
        key = await pool.acquire()
        try:
            payload = _build_payload(url, cfg)
            async with session.post(
                f"{FC_BASE}/scrape",
                json=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=45),
            ) as resp:
                elapsed = time.time() - t0

                if resp.status != 200:
                    body = await resp.text()
                    code = normalize_http_error(resp.status, body)
                    return error_result(idx, code, elapsed, url=url)

                data     = await resp.json()
                success  = data.get("success", False)
                raw_data = data.get("data") or {}

                if not success:
                    msg = data.get("error") or "fc_failed"
                    return error_result(idx, f"fc_failed: {str(msg)[:60]}", elapsed, url=url)

                output = _extract_output(raw_data, cfg)

                # LLM extraction from markdown
                if cfg.get("llm_extract") and "json" in cfg.get("formats", []):
                    md = raw_data.get("markdown") or output.get("fc_markdown") or ""
                    if md:
                        llm_result = await _llm_extract(
                            markdown=md,
                            prompt=cfg.get("json_prompt", DEFAULT_JSON_PROMPT),
                            schema=cfg.get("json_schema", DEFAULT_JSON_SCHEMA),
                            model=cfg.get("llm_model", "google/gemini-2.0-flash-001"),
                            api_key=cfg.get("openrouter_key", ""),
                            session=session,
                        )
                        if llm_result:
                            output.update(_apply_split(llm_result, cfg.get("json_split", True)))

                if not output:
                    return error_result(idx, "api_empty_content", elapsed, url=url)

                return success_result(idx, output, elapsed, url=url)

        except asyncio.TimeoutError:
            elapsed = time.time() - t0
            return error_result(idx, f"api_timeout ({elapsed:.0f}s)", elapsed, url=url)
        except Exception as exc:
            elapsed = time.time() - t0
            return error_result(idx, normalize_exception(exc), elapsed, url=url)


async def _run_batch(
    items: list[dict],
    cfg: dict,
    keys: list[str],
    concurrency: int,
    progress_queue: queue.Queue,
    stop_event: threading.Event,
    result_queue: queue.Queue | None = None,
) -> list[dict]:
    pool    = _KeyPool(keys)
    sem     = asyncio.Semaphore(concurrency)
    results: list[dict] = []
    total   = len(items)
    t0      = time.time()

    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(
                _fetch_one(session, sem, pool, item, cfg, stop_event)
            )
            for item in items
        ]
        for coro in asyncio.as_completed(tasks):
            if stop_event.is_set():
                for t in tasks:
                    t.cancel()
                break
            result = await coro
            results.append(result)
            if result_queue is not None:
                result_queue.put_nowait(result)
            done    = len(results)
            elapsed = time.time() - t0
            speed   = done / elapsed if elapsed > 0 else 0
            eta     = int((total - done) / speed) if speed > 0 and done < total else 0
            ok      = sum(1 for r in results if r["ok"])
            progress_queue.put_nowait({
                "done": done, "total": total, "ok": ok,
                "errors": done - ok, "speed": speed, "eta": eta,
            })

    return results


# ── Public entry point ─────────────────────────────────────────────────────────

def run_firecrawl_enrichment(
    df: pd.DataFrame,
    url_col: str,
    row_indices: list[int],
    cfg: dict,
    concurrency: int,
    progress_queue: queue.Queue,
    stop_event: threading.Event,
    keys: list[str] | None = None,
    result_queue: queue.Queue | None = None,
) -> tuple[list[dict], int]:
    """
    Runs Firecrawl enrichment synchronously (call inside threading.Thread).
    Returns (results, skipped_count).
    Each result follows core.errors standard schema:
      {"idx", "ok", "data", "error", "elapsed", "url"}
    """
    resolved_keys = keys or _load_keys()
    if not resolved_keys:
        raise RuntimeError("No Firecrawl keys configured. Set FIRECRAWL_KEY_1 in .env")

    items   = []
    skipped = 0
    for idx in row_indices:
        url = str(df.iloc[idx].get(url_col, "")).strip()
        if not url or url in ("nan", "None"):
            skipped += 1
            continue
        items.append({"idx": idx, "url": url})

    results = asyncio.run(_run_batch(
        items=items,
        cfg=cfg,
        keys=resolved_keys,
        concurrency=concurrency,
        progress_queue=progress_queue,
        stop_event=stop_event,
        result_queue=result_queue,
    ))
    return results, skipped

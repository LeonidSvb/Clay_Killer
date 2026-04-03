"""
app/enrichments/exa.py — Exa website enrichment adapter.

Modes:
  summary    — Exa AI generates summary from a query prompt → "Website Summary"
  text       — Raw scraped text, pipe to your LLM           → "Website Text"
  highlights — Relevant excerpts from a query               → "Website Highlights"
  structured — Exa AI returns structured JSON fields        → one col per schema field

Auto-skips rows with empty URL (returns [empty_url] without calling API).
"""

import asyncio
import json
import os
import queue
import threading
import time

import aiohttp
import pandas as pd

CONCURRENCY_DEFAULT = 50

# ── Mode definitions ───────────────────────────────────────────────────────────

MODES: dict[str, str] = {
    "summary":    "Summary (Exa AI)",
    "text":       "Raw Text (pipe to LLM)",
    "highlights": "Highlights",
    "structured": "Structured (multi-column)",
}

OUTPUT_COL: dict[str, str] = {
    "summary":    "Website Summary",
    "text":       "Website Text",
    "highlights": "Website Highlights",
    "structured": "",   # dynamic — one col per schema key
}

DEFAULT_QUERY = (
    "Produce a very detailed, factual summary of up to 1,200 characters.\n\n"
    "GOAL: Extract concrete information that clearly defines the company's ideal customer profile (ICP), "
    "core specialization, primary focus, and explicit differentiation. "
    "Preserve only explicit facts from the site. Eliminate generic language.\n\n"
    "TASK: Rewrite the content into a single continuous summary that captures:\n"
    "- What the company does in specific, practical terms\n"
    "- Its core specialization (primary operational focus)\n"
    "- All services, programs, and offerings mentioned (do not merge or generalize lists)\n"
    "- Explicitly stated ideal client characteristics\n"
    "- Industries, sectors, and company categories explicitly served\n"
    "- Roles or departments targeted as buyers, if stated\n"
    "- How the company explicitly differentiates itself\n"
    "- Delivery model, engagement structure, pricing model, or contract structure if stated\n"
    "- Geographic markets served or limitations, if explicitly stated\n"
    "- Any years, metrics, case examples, certifications, rankings, or proof mentioned\n"
    "- Explicitly state when ICP, specialization, differentiation, geography, scale, or proof is not provided\n\n"
    "RULES: Facts only. No inference. No marketing language. Don't add, omit, or generalize.\n\n"
    "OUTPUT: A single factual summary text. No headings, bullets, or formatting."
)

DEFAULT_HIGHLIGHTS_QUERY = "Key facts about what the company does, who they serve, and how they differentiate."

DEFAULT_STRUCTURED_SCHEMA = {
    "type": "object",
    "properties": {
        "industry":      {"type": "string", "description": "Primary industry or sector"},
        "icp":           {"type": "string", "description": "Ideal customer profile — who they sell to"},
        "specialization":{"type": "string", "description": "Core operational focus"},
        "geography":     {"type": "string", "description": "Geographic markets served"},
        "differentiator":{"type": "string", "description": "How they differentiate from competitors"},
    },
    "required": ["industry", "icp", "specialization"],
}


# ── Payload builder ────────────────────────────────────────────────────────────

def build_payload(url: str, cfg: dict) -> dict:
    mode       = cfg.get("mode", "summary")
    max_age    = cfg.get("max_age_hours", 24)
    query      = cfg.get("query", DEFAULT_QUERY)
    max_chars  = cfg.get("max_chars", 5000)
    verbosity  = cfg.get("verbosity", "standard")
    schema     = cfg.get("schema", DEFAULT_STRUCTURED_SCHEMA)

    base = {"ids": [url], "maxAgeHours": max_age}

    if mode == "summary":
        base["summary"] = {"query": query}
    elif mode == "text":
        base["text"] = {"maxCharacters": max_chars, "verbosity": verbosity}
    elif mode == "highlights":
        base["highlights"] = {"query": query, "maxCharacters": max_chars}
    elif mode == "structured":
        base["summary"] = {"query": query, "schema": schema}

    return base


def extract_output(result: dict, mode: str) -> dict:
    """Extract output dict from a single Exa result item."""
    if mode == "summary":
        text = result.get("summary") or ""
        return {"Website Summary": text} if text else {}

    elif mode == "text":
        text = result.get("text") or ""
        return {"Website Text": text} if text else {}

    elif mode == "highlights":
        items = result.get("highlights") or []
        text = " [...] ".join(items) if isinstance(items, list) else str(items)
        return {"Website Highlights": text} if text else {}

    elif mode == "structured":
        raw = result.get("summary") or ""
        if not raw:
            return {}
        # Exa returns structured as JSON string when schema is provided
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                return {k: str(v) for k, v in parsed.items() if v is not None}
        except (json.JSONDecodeError, TypeError):
            pass
        return {"Website Summary": raw}  # fallback: treat as plain text

    return {}


# ── Async fetcher ──────────────────────────────────────────────────────────────

async def _fetch_one(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    item: dict,
    cfg: dict,
    api_key: str,
    stop_event: threading.Event,
) -> dict:
    idx  = item["idx"]
    url  = item["url"]
    mode = cfg.get("mode", "summary")

    if stop_event.is_set():
        return {"idx": idx, "url": url, "data": {}, "ok": False, "error": "stopped", "elapsed": 0.0}

    # Auto-skip empty / clearly invalid URLs
    if not url or url in ("nan", "None", "http://", "https://"):
        return {"idx": idx, "url": url, "data": {}, "ok": False, "error": "empty_url", "elapsed": 0.0}

    t0 = time.time()
    async with sem:
        try:
            payload = build_payload(url, cfg)
            async with session.post(
                "https://api.exa.ai/contents",
                json=payload,
                headers={"x-api-key": api_key},
                timeout=aiohttp.ClientTimeout(total=90),
            ) as resp:
                elapsed = time.time() - t0
                if resp.status != 200:
                    err_body = await resp.text()
                    return {"idx": idx, "url": url, "data": {}, "ok": False,
                            "error": f"HTTP_{resp.status}: {err_body[:60]}", "elapsed": elapsed}

                data        = await resp.json()
                exa_results = data.get("results", [])

                if not exa_results:
                    return {"idx": idx, "url": url, "data": {}, "ok": False,
                            "error": "no_result", "elapsed": elapsed}

                output = extract_output(exa_results[0], mode)

                if not output:
                    return {"idx": idx, "url": url, "data": {}, "ok": False,
                            "error": "empty_content", "elapsed": elapsed}

                return {"idx": idx, "url": url, "data": output, "ok": True,
                        "error": None, "elapsed": elapsed}

        except asyncio.TimeoutError:
            return {"idx": idx, "url": url, "data": {}, "ok": False,
                    "error": "timeout", "elapsed": time.time() - t0}
        except Exception as e:
            return {"idx": idx, "url": url, "data": {}, "ok": False,
                    "error": str(e)[:100], "elapsed": time.time() - t0}


async def _run_exa_batch(
    items: list[dict],
    cfg: dict,
    api_key: str,
    concurrency: int,
    progress_queue: queue.Queue,
    stop_event: threading.Event,
) -> list[dict]:
    sem     = asyncio.Semaphore(concurrency)
    results: list[dict] = []
    total   = len(items)
    t0      = time.time()

    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(_fetch_one(session, sem, item, cfg, api_key, stop_event))
            for item in items
        ]
        for coro in asyncio.as_completed(tasks):
            if stop_event.is_set():
                for t in tasks:
                    t.cancel()
                break
            result = await coro
            results.append(result)
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

def run_exa_enrichment(
    df: pd.DataFrame,
    url_col: str,
    row_indices: list[int],
    cfg: dict,
    concurrency: int,
    progress_queue: queue.Queue,
    stop_event: threading.Event,
    api_key: str = "",
) -> tuple[list[dict], int]:
    """
    Runs Exa enrichment synchronously (call inside threading.Thread).
    cfg keys: mode, query, max_chars, verbosity, schema, max_age_hours.
    Returns (results, skipped_count).
    results: [{"idx": int, "data": dict, "ok": bool, "error": str|None, "elapsed": float}]
    skipped_count: rows with empty URL that were not sent to API.
    """
    key = api_key or os.getenv("EXA_API_KEY", "")
    items   = []
    skipped = 0
    for idx in row_indices:
        url = str(df.iloc[idx].get(url_col, "")).strip()
        if not url or url in ("nan", "None"):
            skipped += 1
            continue
        items.append({"idx": idx, "url": url})

    results = asyncio.run(_run_exa_batch(
        items=items,
        cfg=cfg,
        api_key=key,
        concurrency=concurrency,
        progress_queue=progress_queue,
        stop_event=stop_event,
    ))
    return results, skipped

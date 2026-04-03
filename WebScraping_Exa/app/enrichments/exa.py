"""
app/enrichments/exa.py — Exa website summary enrichment adapter.

For each row: fetches website summary from Exa AI using a URL column.
Same threading+queue pattern as llm.py and mx.py.

Output: {"Website Summary": "..."} per row.
"""

import asyncio
import os
import queue
import threading
import time

import aiohttp
import pandas as pd

CONCURRENCY_DEFAULT = 50
MAX_AGE_HOURS = 24

DEFAULT_EXA_QUERY = (
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


async def _fetch_one(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    item: dict,
    query: str,
    api_key: str,
    stop_event: threading.Event,
) -> dict:
    idx = item["idx"]
    url = item["url"]
    if stop_event.is_set():
        return {"idx": idx, "data": {}, "ok": False, "error": "stopped", "elapsed": 0.0}
    t0 = time.time()
    async with sem:
        try:
            async with session.post(
                "https://api.exa.ai/contents",
                json={"ids": [url], "maxAgeHours": MAX_AGE_HOURS, "summary": {"query": query}},
                headers={"x-api-key": api_key},
                timeout=aiohttp.ClientTimeout(total=90),
            ) as resp:
                elapsed = time.time() - t0
                if resp.status != 200:
                    err = await resp.text()
                    return {"idx": idx, "data": {}, "ok": False,
                            "error": f"HTTP {resp.status}: {err[:80]}", "elapsed": elapsed}
                data = await resp.json()
                results = data.get("results", [])
                summary = results[0].get("summary") or "" if results else ""
                if summary:
                    return {"idx": idx, "data": {"Website Summary": summary}, "ok": True,
                            "error": None, "elapsed": elapsed}
                return {"idx": idx, "data": {}, "ok": False, "error": "empty_summary", "elapsed": elapsed}
        except asyncio.TimeoutError:
            return {"idx": idx, "data": {}, "ok": False, "error": "timeout",
                    "elapsed": time.time() - t0}
        except Exception as e:
            return {"idx": idx, "data": {}, "ok": False, "error": str(e)[:120],
                    "elapsed": time.time() - t0}


async def _run_exa_batch(
    items: list[dict],
    query: str,
    api_key: str,
    concurrency: int,
    progress_queue: queue.Queue,
    stop_event: threading.Event,
) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    results: list[dict] = []
    total = len(items)
    t0 = time.time()

    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(_fetch_one(session, sem, item, query, api_key, stop_event))
            for item in items
        ]
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


def run_exa_enrichment(
    df: pd.DataFrame,
    url_col: str,
    row_indices: list[int],
    query: str,
    concurrency: int,
    progress_queue: queue.Queue,
    stop_event: threading.Event,
    api_key: str = "",
) -> list[dict]:
    """
    Runs Exa enrichment synchronously (call inside threading.Thread).
    Returns list of {"idx": int, "data": {"Website Summary": str}, "ok": bool, "error": str|None, "elapsed": float}.
    """
    key = api_key or os.getenv("EXA_API_KEY", "")
    items = [
        {"idx": idx, "url": str(df.iloc[idx].get(url_col, "")).strip()}
        for idx in row_indices
    ]
    return asyncio.run(_run_exa_batch(
        items=items,
        query=query,
        api_key=key,
        concurrency=concurrency,
        progress_queue=progress_queue,
        stop_event=stop_event,
    ))

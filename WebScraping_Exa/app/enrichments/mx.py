"""
app/enrichments/mx.py — MX Check enrichment adapter.

For each row: extracts domain from email, queries Google DNS-over-HTTPS,
classifies MX provider (Google, Microsoft, Zoho, custom, etc.).

Same threading+queue pattern as llm.py.
"""

import asyncio
import queue
import re
import threading
import time

import httpx
import pandas as pd

from core.errors import normalize_exception

DOH_URL = "https://dns.google/resolve"

MX_PATTERNS: list[tuple[str, str]] = [
    (r"google\.com$", "Google Workspace"),
    (r"googlemail\.com$", "Google Workspace"),
    (r"outlook\.com$", "Microsoft 365"),
    (r"hotmail\.com$", "Microsoft 365"),
    (r"microsoft\.com$", "Microsoft 365"),
    (r"protection\.outlook\.com$", "Microsoft 365"),
    (r"zoho\.com$", "Zoho"),
    (r"zohomail\.com$", "Zoho"),
    (r"yahoodns\.net$", "Yahoo"),
    (r"yahoo\.com$", "Yahoo"),
    (r"mxroute\.com$", "MXroute"),
    (r"protonmail\.ch$", "Proton Mail"),
    (r"proton\.me$", "Proton Mail"),
    (r"mailgun\.org$", "Mailgun"),
    (r"sendgrid\.net$", "SendGrid"),
    (r"amazonses\.com$", "Amazon SES"),
]


def _extract_domain(email: str) -> str | None:
    email = str(email).strip().lower()
    if "@" not in email:
        return None
    domain = email.split("@", 1)[1].strip()
    if not domain or "." not in domain:
        return None
    return domain


def mx_classify(mx_records: list[str]) -> str:
    for mx in mx_records:
        mx_lower = mx.lower().rstrip(".")
        for pattern, provider in MX_PATTERNS:
            if re.search(pattern, mx_lower):
                return provider
    if mx_records:
        return "Custom / Other"
    return "No MX"


async def _fetch_mx(domain: str, client: httpx.AsyncClient) -> list[str]:
    try:
        resp = await client.get(
            DOH_URL,
            params={"name": domain, "type": "MX"},
            timeout=10.0,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        answers = data.get("Answer", [])
        records = []
        for ans in answers:
            if ans.get("type") == 15:  # MX record type
                # data format: "10 mail.example.com."
                parts = str(ans.get("data", "")).split()
                if len(parts) >= 2:
                    records.append(parts[1])
        return records
    except Exception:
        return []


async def _run_mx_batch(
    items: list[dict],
    concurrency: int,
    progress_queue: queue.Queue,
    stop_event: threading.Event,
) -> list[dict]:
    """
    items: [{"idx": int, "domain": str}, ...]
    Returns: [{"idx": int, "mx_real": str, "mx_provider": str, "ok": bool, "error": str|None}, ...]
    """
    sem = asyncio.Semaphore(concurrency)
    results: list[dict] = []
    total = len(items)
    t0 = time.time()

    # Deduplicate domains — query each domain once
    domain_cache: dict[str, list[str]] = {}

    async def process_item(item: dict) -> dict:
        idx = item["idx"]
        domain = item["domain"]

        if domain is None:
            return {"idx": idx, "mx_real": "", "mx_provider": "No email", "ok": True, "error": None}

        async with sem:
            if stop_event.is_set():
                return {"idx": idx, "mx_real": "", "mx_provider": "", "ok": False, "error": "sys_stopped"}

            if domain not in domain_cache:
                domain_cache[domain] = await _fetch_mx(domain, client)

            mx_records = domain_cache[domain]
            provider = mx_classify(mx_records)
            mx_real = mx_records[0].rstrip(".") if mx_records else ""
            return {"idx": idx, "mx_real": mx_real, "mx_provider": provider, "ok": True, "error": None}

    headers = {"Accept": "application/dns-json"}
    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [asyncio.create_task(process_item(item)) for item in items]
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


def run_mx_enrichment(
    df: pd.DataFrame,
    email_col: str,
    row_indices: list[int],
    concurrency: int,
    progress_queue: queue.Queue,
    stop_event: threading.Event,
) -> list[dict]:
    """
    Runs MX check synchronously (call inside threading.Thread).
    Returns list of {"idx": int, "mx_real": str, "mx_provider": str, "ok": bool, "error": str|None}.
    """
    items = []
    for idx in row_indices:
        row = df.iloc[idx]
        email = str(row.get(email_col, "")).strip()
        domain = _extract_domain(email)
        items.append({"idx": idx, "domain": domain})

    return asyncio.run(_run_mx_batch(
        items=items,
        concurrency=concurrency,
        progress_queue=progress_queue,
        stop_event=stop_event,
    ))

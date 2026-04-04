"""
Compare old focused services prompt vs new combined extraction prompt.
Also spot-checks against raw website text to validate accuracy.
"""

import asyncio
import csv
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.stdout.reconfigure(encoding="utf-8")

API_KEY  = os.getenv("OPENROUTER_API_KEY", "")
BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_ID = "openai/gpt-oss-120b"

INPUT_CSV = r"C:\Users\79818\Downloads\_US+ recruit 10-100  - COPY#2 (2).csv"
NEW_JSONL  = r"C:\Users\79818\Desktop\tests\WebScraping_Exa\icebreakers_round_robin\extractions\extraction_20260404_140011_gpt_oss_120b.jsonl"
OUT_CSV    = r"C:\Users\79818\Desktop\tests\WebScraping_Exa\icebreakers_round_robin\services_comparison.csv"

OLD_PROMPT = """You are a strict classification engine.

Task: determine which SERVICES a company provides.

Identify:
- primary_service (ONE value)
- secondary_services (0-3 values)

Allowed values:
- staffing
- permanent_recruiting
- executive_search
- rpo
- sourcing
- unknown

Definitions:
- staffing → temporary / contract workforce, high-volume hiring
- permanent_recruiting → full-time placement, contingency recruiting
- executive_search → C-level / VP hiring, retained search
- rpo → outsourced recruiting function, embedded recruiters
- sourcing → candidate sourcing / research only

Rules:
- Choose ONE primary_service (dominant positioning or revenue driver)
- secondary_services = additional clearly mentioned services (exclude primary)
- Do NOT duplicate primary_service in secondary_services
- If unclear → primary_service = "unknown", secondary_services = []
- Prefer precision over guessing

Output (JSON):
{{
  "primary_service": "...",
  "secondary_services": [...],
  "service_confidence": 1-10,
  "service_reason": "short explanation based on explicit signals"
}}

Company data:
{desc}
{website}
{summary}
{name}"""


def parse_json(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        result = json.loads(cleaned)
        return result if isinstance(result, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return {}


async def run_old_prompt(rows: list[dict]) -> list[dict]:
    sem = asyncio.Semaphore(15)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    results = [None] * len(rows)

    async def one(i: int, row: dict):
        prompt = OLD_PROMPT.format(
            desc    = row.get("Company Short Description (68%)", "") or "",
            website = row.get("Company Website (100%)", "") or "",
            summary = row.get("Website Summary (100%)", "") or "",
            name    = row.get("COMPANY NAME", "") or "",
        )
        async with sem:
            resp = await client.post(
                BASE_URL,
                json={"model": MODEL_ID, "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.1, "provider": {"sort": "throughput"}},
                timeout=90,
            )
        raw = resp.json()["choices"][0]["message"]["content"]
        return i, parse_json(raw)

    done = 0
    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [asyncio.create_task(one(i, row)) for i, row in enumerate(rows)]
        for coro in asyncio.as_completed(tasks):
            i, r = await coro
            results[i] = r
            done += 1
            print(f"  old prompt: {done}/{len(rows)}", end="\r")

    print()
    return results


def main():
    # load CSV
    with open(INPUT_CSV, encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    sample = all_rows[:100]

    # load new extraction
    new_ext = {}
    with open(NEW_JSONL, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                new_ext[r["_idx"]] = r

    print(f"Running old focused services prompt on 100 leads...")
    old_results = asyncio.run(run_old_prompt(sample))

    # ── comparison stats ─────────────────────────────────────────────────────
    old_primary = Counter(r.get("primary_service", "") for r in old_results if r)
    new_primary = Counter(new_ext[i].get("primary_service", "") for i in range(100) if i in new_ext)

    print("\n=== SERVICE DISTRIBUTION COMPARISON ===\n")
    print(f"{'Service':<26} {'OLD':>6} {'NEW':>6} {'DIFF':>6}")
    print("-" * 48)
    all_svcs = sorted(set(list(old_primary.keys()) + list(new_primary.keys())))
    for s in all_svcs:
        o = old_primary.get(s, 0)
        n = new_primary.get(s, 0)
        diff = n - o
        sign = "+" if diff > 0 else ""
        print(f"{s:<26} {o:>6} {n:>6} {sign+str(diff):>6}")

    # ── disagreements ─────────────────────────────────────────────────────────
    disagree = []
    for i in range(100):
        if not old_results[i] or i not in new_ext:
            continue
        old_s = old_results[i].get("primary_service", "?")
        new_s = new_ext[i].get("primary_service", "?")
        if old_s != new_s:
            disagree.append({
                "idx":         i,
                "company":     sample[i].get("COMPANY NAME", ""),
                "old_service": old_s,
                "new_service": new_s,
                "old_conf":    old_results[i].get("service_confidence", "?"),
                "old_reason":  old_results[i].get("service_reason", "")[:100],
                "new_reasoning": new_ext[i].get("reasoning", "")[:100],
                "website_snippet": (sample[i].get("Website Summary (100%)", "") or "")[:200],
            })

    print(f"\n=== DISAGREEMENTS: {len(disagree)}/100 ===\n")
    for d in disagree:
        print(f"[{d['idx']:2d}] {d['company'][:35]:<35}")
        print(f"     OLD: {d['old_service']:<22} NEW: {d['new_service']}")
        print(f"     OLD reason: {d['old_reason']}")
        print(f"     Website: {d['website_snippet'][:120]}")
        print()

    # ── agreement rate ────────────────────────────────────────────────────────
    agree = 100 - len(disagree)
    print(f"Agreement rate: {agree}/100 ({agree}%)")

    # ── secondary services comparison ─────────────────────────────────────────
    old_has_secondary = sum(1 for r in old_results if r and r.get("secondary_services"))
    new_has_secondary = sum(1 for i in range(100) if new_ext.get(i, {}).get("secondary_services"))
    print(f"\nHas secondary_services — OLD: {old_has_secondary}/100 | NEW: {new_has_secondary}/100")

    # ── save comparison CSV ───────────────────────────────────────────────────
    fields = [
        "idx", "company_name", "company_website",
        "old_primary", "old_secondary", "old_confidence", "old_reason",
        "new_primary", "new_secondary", "new_reasoning",
        "agree", "website_snippet",
    ]

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for i in range(100):
            if not old_results[i] or i not in new_ext:
                continue
            old_r = old_results[i]
            new_r = new_ext[i]
            old_s = old_r.get("primary_service", "")
            new_s = new_r.get("primary_service", "")
            old_sec = old_r.get("secondary_services", [])
            new_sec = new_r.get("secondary_services", [])
            writer.writerow({
                "idx":            i,
                "company_name":   sample[i].get("COMPANY NAME", ""),
                "company_website":sample[i].get("Company Website (100%)", ""),
                "old_primary":    old_s,
                "old_secondary":  ", ".join(old_sec) if isinstance(old_sec, list) else str(old_sec),
                "old_confidence": old_r.get("service_confidence", ""),
                "old_reason":     old_r.get("service_reason", ""),
                "new_primary":    new_s,
                "new_secondary":  ", ".join(new_sec) if isinstance(new_sec, list) else str(new_sec),
                "new_reasoning":  new_r.get("reasoning", ""),
                "agree":          "YES" if old_s == new_s else "NO",
                "website_snippet":(sample[i].get("Website Summary (100%)", "") or "")[:300],
            })

    print(f"\nSaved: {OUT_CSV}")


if __name__ == "__main__":
    main()

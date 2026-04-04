"""
icebreakers_round_robin/run_canada_extraction.py

Runs LLM extraction for Canada leads using data already in DB.
Saves primary_service / sub_industry / client_profile back to DB.
Saves extraction JSONL for icebreaker generation.

Usage:
  py icebreakers_round_robin/run_canada_extraction.py
  py icebreakers_round_robin/run_canada_extraction.py --mx google other
  py icebreakers_round_robin/run_canada_extraction.py --sample 20
  py icebreakers_round_robin/run_canada_extraction.py --stats-only
"""

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.stdout.reconfigure(encoding="utf-8")

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_ID       = "openai/gpt-oss-120b"

THIS_DIR    = Path(__file__).parent
DB_PATH     = THIS_DIR.parent / "data" / "leads.db"
EXTRACT_DIR = THIS_DIR / "extractions"

EXTRACTION_PROMPT = (THIS_DIR / "extraction_prompt_final.txt").read_text(encoding="utf-8")


def parse_json(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        result = json.loads(cleaned)
        return result if isinstance(result, dict) else {}
    except Exception:
        pass
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return {}


def build_prompt(row: dict) -> str:
    p = EXTRACTION_PROMPT
    p = p.replace("{{Website Summary}}",          row.get("website_summary") or "")
    p = p.replace("{{Company Short Description}}", row.get("company_short_description") or "")
    p = p.replace("{{Company Name}}",              row.get("company_name") or "")
    p = p.replace("{{Company Website}}",           row.get("company_website") or "")
    p = p.replace("{{Keywords}}",                  row.get("keywords") or "")
    return p


async def call_llm(client: httpx.AsyncClient, sem: asyncio.Semaphore, prompt: str) -> tuple[dict, float]:
    t0 = time.monotonic()
    payload = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "provider": {"sort": "throughput"},
    }
    try:
        async with sem:
            resp = await client.post(OPENROUTER_URL, json=payload, timeout=90.0)
            elapsed = time.monotonic() - t0
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}"}, elapsed
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            return parse_json(content or ""), elapsed
    except Exception as e:
        return {"error": str(e)[:100]}, time.monotonic() - t0


async def run_extraction(rows: list[dict], concurrency: int) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
    results = []
    done = 0
    t0 = time.time()

    async def one(row: dict) -> dict:
        extracted, elapsed = await call_llm(client, sem, build_prompt(row))
        return {**row, **extracted, "_t_s": round(elapsed, 2)}

    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [asyncio.create_task(one(r)) for r in rows]
        for coro in asyncio.as_completed(tasks):
            r = await coro
            results.append(r)
            done += 1
            speed = done / max(time.time() - t0, 0.1)
            print(f"  {done}/{len(rows)} | {speed:.1f}/s", end="\r")

    print()
    results.sort(key=lambda x: x.get("_idx", 0))
    return results


def print_stats(results: list[dict]):
    total = len(results)
    errors = sum(1 for r in results if r.get("error"))
    print(f"\n{'='*60}")
    print(f"EXTRACTION STATS — {total} rows | errors={errors}")
    print(f"{'='*60}")

    for field in ["primary_service", "sub_industry", "client_profile", "extractability"]:
        counts = Counter(r.get(field) or "null" for r in results)
        print(f"\n{field}:")
        for val, n in counts.most_common(12):
            bar = "#" * int(n / total * 30)
            print(f"  {val:<30} {n:>4}  {n/total*100:>5.1f}%  {bar}")

    # matrix key preview
    matrix_keys = Counter(
        f"{r.get('primary_service') or 'unknown'}__{r.get('sub_industry') or 'null'}"
        for r in results if not r.get("error")
    )
    generic = matrix_keys.get("unknown__null", 0)
    specific = total - errors - generic
    print(f"\nMATRIX BREAKDOWN:")
    print(f"  specific (non-generic): {specific}/{total-errors} ({specific/(total-errors)*100:.0f}%)")
    print(f"  generic (unknown__null): {generic}/{total-errors} ({generic/(total-errors)*100:.0f}%)")
    print(f"\nTop matrix keys:")
    for key, n in matrix_keys.most_common(10):
        print(f"  {key:<40} {n}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mx",          nargs="+", default=["google", "other"])
    parser.add_argument("--concurrency", type=int,  default=40)
    parser.add_argument("--sample",      type=int,  default=None)
    parser.add_argument("--stats-only",  action="store_true")
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    mx_placeholders = ",".join("?" * len(args.mx))
    cur.execute(f"""
        SELECT DISTINCT
            c.domain, c.company_name, c.clean_company, c.company_website,
            c.company_short_description, c.website_summary, c.keywords,
            c.primary_service, c.sub_industry, c.client_profile
        FROM leads l
        JOIN companies c ON l.domain = c.domain
        WHERE l.country = 'Canada'
        AND l.lead_vertical = 'recruit'
        AND c.mx_provider IN ({mx_placeholders})
    """, args.mx)
    company_rows = [dict(r) for r in cur.fetchall()]

    if args.sample:
        company_rows = company_rows[:args.sample]

    print(f"Canada {'+'.join(args.mx)} recruit companies: {len(company_rows)}")
    already = sum(1 for r in company_rows if r.get("primary_service"))
    print(f"  already have primary_service: {already}")
    print(f"  need extraction: {len(company_rows) - already}")

    if args.stats_only:
        # just show current state
        print_stats(company_rows)
        con.close()
        return

    for i, r in enumerate(company_rows):
        r["_idx"] = i

    print(f"\nRunning extraction (model={MODEL_ID}, concurrency={args.concurrency})...")
    t0 = time.time()
    results = asyncio.run(run_extraction(company_rows, concurrency=args.concurrency))
    print(f"Done in {time.time()-t0:.1f}s")

    print_stats(results)

    # ── update DB ──────────────────────────────────────────────────────────────
    updated = 0
    for r in results:
        if r.get("error"):
            continue
        ps  = r.get("primary_service")
        sub = r.get("sub_industry")
        cp  = r.get("client_profile")
        if not any([ps, sub, cp]):
            continue
        cur.execute("""
            UPDATE companies SET
                primary_service = COALESCE(primary_service, ?),
                sub_industry    = COALESCE(sub_industry, ?),
                client_profile  = COALESCE(client_profile, ?),
                extracted_at    = datetime('now')
            WHERE domain = ?
        """, (ps, sub, cp, r["domain"]))
        if cur.rowcount:
            updated += 1

    con.commit()
    print(f"\nDB updated: {updated} companies")

    # ── save extraction JSONL for icebreaker gen ───────────────────────────────
    EXTRACT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # join with lead data for icebreaker generation
    mx_ph = ",".join("?" * len(args.mx))
    cur.execute(f"""
        SELECT l.first_name, l.last_name, l.email, l.linkedin_url, l.headline, l.state,
               c.domain, c.company_name, c.clean_company, c.company_website,
               c.company_linkedin_url, c.primary_service, c.sub_industry, c.client_profile
        FROM leads l
        JOIN companies c ON l.domain = c.domain
        WHERE l.country = 'Canada'
        AND l.lead_vertical = 'recruit'
        AND c.mx_provider IN ({mx_ph})
        AND (l.email_validation_status IS NULL OR l.email_validation_status != 'invalid')
        ORDER BY l.first_name
    """, args.mx)
    lead_rows = cur.fetchall()
    lead_cols = [d[0] for d in cur.description]

    # map domain → extracted data
    domain_to_extracted = {r["domain"]: r for r in results}

    jsonl_path = EXTRACT_DIR / f"canada_extracted_{ts}.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for i, row in enumerate(lead_rows):
            d = dict(zip(lead_cols, row))
            ext = domain_to_extracted.get(d["domain"], {})
            record = {
                "_idx":             i,
                "_first_name":      d["first_name"] or "",
                "_last_name":       d["last_name"] or "",
                "_email":           d["email"] or "",
                "_linkedin":        d["linkedin_url"] or "",
                "_company_linkedin":d["company_linkedin_url"] or "",
                "_company_name":    d["company_name"] or "",
                "_clean_company":   d["clean_company"] or d["company_name"] or "",
                "_country":         "Canada",
                "_state":           d["state"] or "",
                "_headline":        d["headline"] or "",
                "primary_service":  ext.get("primary_service") or d.get("primary_service") or "unknown",
                "sub_industry":     ext.get("sub_industry")    or d.get("sub_industry")    or "null",
                "client_profile":   ext.get("client_profile")  or d.get("client_profile")  or "unknown",
                "detected_signals": ext.get("detected_signals") or "",
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Saved: {jsonl_path.name} ({len(lead_rows)} leads)")
    print(f"\nNext:")
    print(f"  py icebreakers_round_robin/run_canada.py --from-jsonl {jsonl_path}")

    con.close()


if __name__ == "__main__":
    main()

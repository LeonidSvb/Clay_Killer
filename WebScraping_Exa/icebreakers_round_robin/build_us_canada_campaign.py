"""
icebreakers_round_robin/build_us_canada_campaign.py

Builds merged US + Canada recruit campaign file.

Steps:
  1. Load US ab_test (already has icebreakers), patch clean_company from DB
  2. Pull Canada Google/Other leads from DB, generate extraction JSONL
  3. After Canada icebreakers are generated (run_canada.py --from-jsonl),
     merge into one final CSV

Usage:
  # Step 1: build US-only file + Canada extraction JSONL
  py icebreakers_round_robin/build_us_canada_campaign.py --prepare

  # Step 2 (after OpenRouter top-up + run_canada.py):
  py icebreakers_round_robin/build_us_canada_campaign.py --merge
"""

import argparse
import asyncio
import csv
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.stdout.reconfigure(encoding="utf-8")

_OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
_NORM_SYSTEM = """Normalize the company name to the core brand employees actually use in casual conversation.

Rules:
* 1-2 words maximum
* If the name is already clean and distinctive — a single compound word, an acronym, or a 2-word brand with no generic terms — return it exactly as-is
* Remove generic terms only when they are not part of the core brand: Recruitment, Staffing, Ltd, Inc, LLC, Group, Services, Global, International, Consulting, Solutions, Partners, Associates
* Never invent abbreviations — only use an acronym if the company itself uses it
* Preserve original capitalization
* Prefer the name employees would casually say to friends

Output:
Return only the cleaned name. No explanations."""


async def _llm_normalize_batch(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """(domain, company_name) -> {domain: clean_name}"""
    results = {}
    sem = asyncio.Semaphore(50)
    headers = {"Authorization": f"Bearer {_OPENROUTER_KEY}", "Content-Type": "application/json"}

    async def one(domain, name):
        async with sem:
            try:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json={"model": "openai/gpt-4o-mini",
                          "messages": [{"role": "system", "content": _NORM_SYSTEM},
                                       {"role": "user", "content": f"Domain: {domain}\nCompany name: {name}"}],
                          "temperature": 0.0, "provider": {"sort": "throughput"}},
                    timeout=30.0)
                if resp.status_code == 200:
                    return domain, resp.json()["choices"][0]["message"]["content"].strip()
            except Exception:
                pass
            return domain, name

    async with httpx.AsyncClient(headers=headers) as client:
        for coro in asyncio.as_completed([asyncio.create_task(one(d, n)) for d, n in pairs]):
            domain, clean = await coro
            results[domain] = clean
    return results

THIS_DIR     = Path(__file__).parent
DB_PATH      = THIS_DIR.parent / "data" / "leads.db"
CAMP_DIR     = THIS_DIR / "campaigns"
EXTRACT_DIR  = THIS_DIR / "extractions"

US_AB_TEST   = CAMP_DIR / "us_ab_test_20260404.csv"
CANADA_JSONL = EXTRACT_DIR / "canada_for_icebreaker.jsonl"
OUT_DATE     = datetime.now().strftime("%Y%m%d")


def make_clean(name: str) -> str | None:
    if not name:
        return None
    for sep in [" | ", " - Gateway", " - Contingent", " - Staffing", " - Recruiting"]:
        if sep in name:
            name = name.split(sep)[0].strip()
    if "|" in name:
        name = name.split("|")[0].strip()
    name = re.sub(r"[^\x00-\x7F\u00C0-\u024F\u0400-\u04FF]", "", name).strip()
    if len(name) > 50:
        parts = re.split(r"\s[-]\s", name, maxsplit=1)
        if len(parts) > 1 and len(parts[0]) > 5:
            name = parts[0].strip()
    # reject obvious garbage
    garbage_signals = ["could you please", "quick intro", "provide the company"]
    if any(g in name.lower() for g in garbage_signals):
        return None
    return name or None


def load_db_company(domain: str, cur) -> dict:
    cur.execute(
        "SELECT clean_company, company_name, primary_service, sub_industry FROM companies WHERE domain = ?",
        (domain,)
    )
    row = cur.fetchone()
    if row:
        return {"clean_company": row[0], "company_name": row[1],
                "primary_service": row[2], "sub_industry": row[3]}
    return {}


def extract_domain(url: str) -> str | None:
    if not url:
        return None
    url = url.strip().lower()
    url = re.sub(r"^https?://", "", url)
    url = url.split("/")[0].split("?")[0]
    url = re.sub(r"^www\.", "", url)
    return url or None


# ── STEP 1: prepare ────────────────────────────────────────────────────────────

def prepare(con: sqlite3.Connection):
    cur = con.cursor()

    # ── load US ab test ──────────────────────────────────────────────────────
    us_rows = list(csv.DictReader(open(US_AB_TEST, encoding="utf-8")))
    print(f"US ab_test: {len(us_rows)} rows")

    fixed_clean = 0
    removed_garbage = []
    removed_errors = []
    us_clean = []

    for r in us_rows:
        # refresh clean_company from DB when available
        email = r.get("email", "")
        domain = email.split("@")[-1].lower() if "@" in email else None
        db = load_db_company(domain, cur) if domain else {}
        if db.get("clean_company"):
            r["clean_company"] = db["clean_company"]
            fixed_clean += 1
        elif not r.get("clean_company", "").strip() or any(
            g in r.get("clean_company", "").lower()
            for g in ["could you please", "quick intro", "provide the company"]
        ):
            r["clean_company"] = make_clean(r.get("company_name", "")) or r.get("company_name", "")
            fixed_clean += 1

    for r in us_rows:
        # drop rows with garbage clean_company
        if any(g in r.get("clean_company", "").lower()
               for g in ["could you please", "quick intro", "provide the company"]):
            removed_garbage.append(r["email"])
            continue

        # drop rows with ERROR icebreaker
        if str(r.get("icebreaker", "")).startswith("ERROR") or not r.get("icebreaker", "").strip():
            removed_errors.append(r["email"])
            continue

        us_clean.append(r)

    print(f"  fixed clean_company: {fixed_clean}")
    print(f"  removed (garbage name): {len(removed_garbage)}")
    print(f"  removed (error icebreaker): {len(removed_errors)} → need re-run after top-up")
    if removed_errors:
        for e in removed_errors:
            print(f"    {e}")
    print(f"  US usable: {len(us_clean)}")

    # ── pull Canada from DB ──────────────────────────────────────────────────
    cur.execute("""
        SELECT l.first_name, l.last_name, l.email, l.linkedin_url,
               c.company_linkedin_url, c.company_name, c.clean_company,
               l.country, l.state, l.headline,
               c.primary_service, c.sub_industry, c.client_profile,
               c.website_summary, c.company_short_description,
               c.keywords, c.company_website, c.domain
        FROM leads l
        JOIN companies c ON l.domain = c.domain
        WHERE l.lead_vertical = 'recruit'
        AND l.country = 'Canada'
        AND c.mx_provider IN ('google', 'other')
        AND (l.email_validation_status IS NULL OR l.email_validation_status != 'invalid')
        ORDER BY l.first_name
    """)
    ca_rows = cur.fetchall()
    ca_cols = [d[0] for d in cur.description]
    print(f"\nCanada Google/Other: {len(ca_rows)} leads")

    # save Canada extraction JSONL
    EXTRACT_DIR.mkdir(exist_ok=True)
    with open(CANADA_JSONL, "w", encoding="utf-8") as f:
        for i, row in enumerate(ca_rows):
            d = dict(zip(ca_cols, row))
            record = {
                "_idx":             i,
                "_first_name":      d["first_name"] or "",
                "_last_name":       d["last_name"] or "",
                "_company_name":    d["company_name"] or "",
                "_company_website": d["company_website"] or "",
                "_country":         d["country"] or "Canada",
                "_email":           d["email"] or "",
                "_linkedin":        d["linkedin_url"] or "",
                "_company_linkedin":d["company_linkedin_url"] or "",
                "_headline":        d["headline"] or "",
                "_clean_company":   d["clean_company"] or d["company_name"] or "",
                # extraction fields for icebreaker
                "primary_service":  d["primary_service"] or "unknown",
                "sub_industry":     d["sub_industry"] or "null",
                "client_profile":   d["client_profile"] or "unknown",
                "detected_signals": "",
                # website data for extraction
                "_website_summary": d["website_summary"] or "",
                "_company_desc":    d["company_short_description"] or "",
                "_keywords":        d["keywords"] or "",
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"  Saved: {CANADA_JSONL.name}")

    # save patched US file
    us_out = CAMP_DIR / f"us_patched_{OUT_DATE}.csv"
    if us_clean:
        fields = list(us_clean[0].keys())
        with open(us_out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(us_clean)
        print(f"\nSaved US patched: {us_out.name} ({len(us_clean)} rows)")

    print(f"\nNext step:")
    print(f"  1. Top up OpenRouter")
    print(f"  2. py icebreakers_round_robin/run_canada.py --from-jsonl {CANADA_JSONL}")
    print(f"  3. py icebreakers_round_robin/build_us_canada_campaign.py --merge")


# ── STEP 2: merge ─────────────────────────────────────────────────────────────

def merge():
    # find latest Canada campaign CSV
    canada_files = sorted(
        [f for f in CAMP_DIR.glob("canada_ab_test_*.csv")],
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )
    if not canada_files:
        print("ERROR: No canada_ab_test_*.csv found. Run run_canada.py first.")
        return
    canada_csv = canada_files[0]
    print(f"Canada source: {canada_csv.name}")

    # find patched US CSV
    us_files = sorted(
        [f for f in CAMP_DIR.glob("us_patched_*.csv")],
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )
    if not us_files:
        print("ERROR: No us_patched_*.csv found. Run --prepare first.")
        return
    us_csv = us_files[0]
    print(f"US source: {us_csv.name}")

    us_rows   = list(csv.DictReader(open(us_csv,    encoding="utf-8")))
    ca_rows   = list(csv.DictReader(open(canada_csv, encoding="utf-8")))

    # filter Canada: only Google/Other, no ERROR icebreakers
    ca_clean = [r for r in ca_rows
                if not str(r.get("icebreaker", "")).startswith("ERROR")
                and r.get("icebreaker", "").strip()]
    errors = len(ca_rows) - len(ca_clean)
    if errors:
        print(f"  Canada: dropped {errors} ERROR icebreaker rows")

    # harmonize column names
    OUTPUT_COLS = [
        "first_name", "last_name", "email", "linkedin_url", "company_linkedin_url",
        "company_name", "clean_company", "country", "state", "headline",
        "primary_service", "sub_industry", "matrix_key", "matrix_pain",
        "icebreaker", "email_a_dealflow", "email_b_lowercase",
    ]

    merged = []
    for r in us_rows:
        merged.append({c: r.get(c, "") for c in OUTPUT_COLS})
    for r in ca_clean:
        merged.append({c: r.get(c, "") for c in OUTPUT_COLS})

    out_path = CAMP_DIR / f"us_canada_ab_test_{OUT_DATE}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(merged)

    us_count = len(us_rows)
    ca_count = len(ca_clean)
    print(f"\nMerged: {out_path.name}")
    print(f"  US: {us_count} | Canada: {ca_count} | Total: {us_count + ca_count}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--merge",   action="store_true")
    args = parser.parse_args()

    if not args.prepare and not args.merge:
        parser.print_help()
        return

    con = sqlite3.connect(DB_PATH)
    if args.prepare:
        prepare(con)
    if args.merge:
        merge()
    con.close()


if __name__ == "__main__":
    main()

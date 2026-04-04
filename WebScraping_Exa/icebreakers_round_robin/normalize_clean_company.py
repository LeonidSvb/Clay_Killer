"""
icebreakers_round_robin/normalize_clean_company.py

Normalizes clean_company for all companies in a campaign CSV via LLM.
Input per request: company domain + original company name.
Updates companies.clean_company in DB.

Usage:
  py icebreakers_round_robin/normalize_clean_company.py --csv icebreakers_round_robin/campaigns/us_patched_20260404.csv
  py icebreakers_round_robin/normalize_clean_company.py --csv icebreakers_round_robin/campaigns/canada_ab_test_20260404.csv
  py icebreakers_round_robin/normalize_clean_company.py --csv icebreakers_round_robin/campaigns/us_canada_ab_test_20260404.csv
  py icebreakers_round_robin/normalize_clean_company.py --all-recruit   (all recruit companies in DB)
"""

import argparse
import asyncio
import csv
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.stdout.reconfigure(encoding="utf-8")

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_ID       = "openai/gpt-4o-mini"   # cheap + fast for simple normalization

DB_PATH = Path(__file__).parent.parent / "data" / "leads.db"

SYSTEM_PROMPT = """Normalize the company name to the core brand employees actually use in casual conversation.

Rules:
* 1-2 words maximum
* If the name is already clean and distinctive — a single compound word, an acronym, or a 2-word brand with no generic terms — return it exactly as-is
* Remove generic terms only when they are not part of the core brand: Recruitment, Staffing, Ltd, Inc, LLC, Group, Services, Global, International, Consulting, Solutions, Partners, Associates
* Never invent abbreviations — only use an acronym if the company itself uses it
* Preserve original capitalization
* Prefer the name employees would casually say to friends

Output:
Return only the cleaned name. No explanations."""


def extract_domain(url: str) -> str | None:
    if not url:
        return None
    url = url.strip().lower()
    url = re.sub(r"^https?://", "", url)
    url = url.split("/")[0].split("?")[0]
    url = re.sub(r"^www\.", "", url)
    return url or None


async def normalize_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    domain: str,
    company_name: str,
) -> tuple[str, str]:
    """Returns (domain, normalized_name)."""
    user_msg = f"Domain: {domain}\nCompany name: {company_name}"
    payload = {
        "model": MODEL_ID,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        "temperature": 0.0,
        "provider": {"sort": "throughput"},
    }
    async with sem:
        try:
            resp = await client.post(OPENROUTER_URL, json=payload, timeout=30.0)
            if resp.status_code != 200:
                return domain, company_name  # fallback to original
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            return domain, content or company_name
        except Exception:
            return domain, company_name


async def run_batch(items: list[tuple[str, str]], concurrency: int) -> dict[str, str]:
    """Returns {domain: clean_name}."""
    sem = asyncio.Semaphore(concurrency)
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
    results = {}
    done = 0
    t0 = time.time()

    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [asyncio.create_task(normalize_one(client, sem, d, n)) for d, n in items]
        for coro in asyncio.as_completed(tasks):
            domain, clean = await coro
            results[domain] = clean
            done += 1
            speed = done / max(time.time() - t0, 0.1)
            print(f"  {done}/{len(items)} | {speed:.1f}/s", end="\r")

    print()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv",         type=str, default=None)
    parser.add_argument("--all-recruit", action="store_true")
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--overwrite",   action="store_true",
                        help="Overwrite existing clean_company (default: only fill missing/bad ones)")
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    if args.csv:
        path = Path(args.csv)
        rows = list(csv.DictReader(open(path, encoding="utf-8")))
        # collect unique domain → company_name pairs
        seen = {}
        for r in rows:
            cn = r.get("company_name") or r.get("Company Name") or ""
            email = r.get("email") or r.get("Email") or ""
            domain = email.split("@")[-1].lower() if "@" in email else ""
            if not domain:
                website = r.get("company_website") or r.get("Company Website") or ""
                domain = extract_domain(website) or ""
            if domain and cn and domain not in seen:
                seen[domain] = cn
        items = list(seen.items())
        print(f"CSV: {path.name} | unique domains: {len(items)}")

    elif args.all_recruit:
        cur.execute("""
            SELECT DISTINCT c.domain, c.company_name
            FROM companies c
            JOIN leads l ON l.domain = c.domain
            WHERE l.lead_vertical = 'recruit'
            AND c.company_name IS NOT NULL
        """)
        items = [(r[0], r[1]) for r in cur.fetchall()]
        print(f"All recruit companies: {len(items)}")

    else:
        parser.print_help()
        con.close()
        return

    if not args.overwrite:
        # only process domains without clean_company or where it looks suspicious
        filtered = []
        for domain, company_name in items:
            cur.execute("SELECT clean_company FROM companies WHERE domain=?", (domain,))
            row = cur.fetchone()
            existing = (row[0] or "").strip() if row else ""
            if not existing:
                filtered.append((domain, company_name))
                continue
            # suspicious: no word overlap with company_name
            cn_words = set(re.findall(r'[a-z]{3,}', company_name.lower()))
            cc_words = set(re.findall(r'[a-z]{3,}', existing.lower()))
            if not (cn_words & cc_words) and len(existing) > 4:
                filtered.append((domain, company_name))
        print(f"Need normalization (missing or suspicious): {len(filtered)}")
        items = filtered
    else:
        print(f"Overwrite mode: normalizing all {len(items)}")

    if not items:
        print("Nothing to do.")
        con.close()
        return

    print(f"Running LLM normalization (model={MODEL_ID}, concurrency={args.concurrency})...")
    t0 = time.time()
    results = asyncio.run(run_batch(items, concurrency=args.concurrency))
    print(f"Done in {time.time()-t0:.1f}s")

    # show sample
    print("\nSample (first 20):")
    for domain, clean in list(results.items())[:20]:
        orig = dict(items).get(domain, "")
        print(f"  {orig[:40]:<40}  ->  {clean}")

    # update DB
    updated = 0
    for domain, clean in results.items():
        cur.execute(
            "UPDATE companies SET clean_company=? WHERE domain=?",
            (clean, domain)
        )
        if cur.rowcount:
            updated += 1

    con.commit()
    print(f"\nDB updated: {updated} companies")
    con.close()


if __name__ == "__main__":
    main()

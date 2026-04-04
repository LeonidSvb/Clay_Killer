"""
icebreakers_round_robin/enrich_exa_summaries.py

Fetches Exa AI website summaries for companies missing them in the DB.
Writes results back to companies.website_summary.

Usage:
  py icebreakers_round_robin/enrich_exa_summaries.py --vertical recruit --country Canada
  py icebreakers_round_robin/enrich_exa_summaries.py --vertical recruit --country Canada --mx google other
  py icebreakers_round_robin/enrich_exa_summaries.py --domains-only   (print missing domains and exit)
"""

import argparse
import asyncio
import os
import sqlite3
import sys
import time
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")

load_dotenv(Path(__file__).parent.parent / ".env")

DB_PATH     = Path(__file__).parent.parent / "data" / "leads.db"
CONCURRENCY = 20
TIMEOUT_S   = 90

EXA_QUERY = (
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
    "OUTPUT: A single factual summary text. No headings, bullets, or formatting."
)


async def fetch_summary(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    domain: str,
    website: str,
    api_key: str,
) -> dict:
    url = website.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    async with sem:
        try:
            payload = {
                "ids": [url],
                "maxAgeHours": 168,
                "summary": {"query": EXA_QUERY},
            }
            async with session.post(
                "https://api.exa.ai/contents",
                json=payload,
                headers={"x-api-key": api_key},
                timeout=aiohttp.ClientTimeout(total=TIMEOUT_S),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    return {"domain": domain, "ok": False, "error": f"HTTP {resp.status}: {body[:80]}"}

                data = await resp.json()
                results = data.get("results", [])
                if not results:
                    return {"domain": domain, "ok": False, "error": "no_result"}

                summary = results[0].get("summary", "")
                if not summary:
                    return {"domain": domain, "ok": False, "error": "empty_summary"}

                return {"domain": domain, "ok": True, "summary": summary}

        except asyncio.TimeoutError:
            return {"domain": domain, "ok": False, "error": "timeout"}
        except Exception as e:
            return {"domain": domain, "ok": False, "error": str(e)[:80]}


async def run_batch(items: list[dict], api_key: str) -> list[dict]:
    sem = asyncio.Semaphore(CONCURRENCY)
    results = []
    done = 0
    t0 = time.time()

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            asyncio.create_task(fetch_summary(session, sem, item["domain"], item["website"], api_key))
            for item in items
        ]
        for coro in asyncio.as_completed(tasks):
            r = await coro
            results.append(r)
            done += 1
            ok = sum(1 for x in results if x["ok"])
            speed = done / max(time.time() - t0, 0.1)
            eta = int((len(items) - done) / speed) if speed > 0 else 0
            print(f"  {done}/{len(items)} | ok={ok} | {speed:.1f}/s | eta={eta}s", end="\r")

    print()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vertical", default=None, help="e.g. recruit or logistic")
    parser.add_argument("--country",  default=None, help="e.g. Canada")
    parser.add_argument("--mx",       nargs="+", default=None, help="mx_provider filter e.g. google other")
    parser.add_argument("--domains-only", action="store_true", help="print missing domains and exit")
    args = parser.parse_args()

    api_key = os.getenv("EXA_API_KEY", "")
    if not api_key and not args.domains_only:
        print("ERROR: EXA_API_KEY not set")
        return

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Build query for companies missing website_summary
    where = ["c.website_summary IS NULL", "c.company_website IS NOT NULL", "c.company_website != ''"]
    params = []

    if args.vertical or args.country or args.mx:
        # join through leads
        from_clause = "FROM companies c JOIN leads l ON l.domain = c.domain"
        if args.vertical:
            where.append("l.lead_vertical = ?")
            params.append(args.vertical)
        if args.country:
            where.append("l.country = ?")
            params.append(args.country)
        if args.mx:
            placeholders = ",".join("?" * len(args.mx))
            where.append(f"c.mx_provider IN ({placeholders})")
            params.extend(args.mx)
        sql = f"SELECT DISTINCT c.domain, c.company_website {from_clause} WHERE {' AND '.join(where)}"
    else:
        sql = f"SELECT domain, company_website FROM companies WHERE {' AND '.join(where)}"

    cur.execute(sql, params)
    rows = cur.fetchall()
    print(f"Missing website_summary: {len(rows)}")

    if args.domains_only:
        for domain, website in rows:
            print(f"  {domain}: {website}")
        con.close()
        return

    if not rows:
        print("Nothing to fetch.")
        con.close()
        return

    items = [{"domain": domain, "website": website} for domain, website in rows]

    print(f"Fetching {len(items)} summaries via Exa AI (concurrency={CONCURRENCY})...\n")
    t0 = time.time()
    results = asyncio.run(run_batch(items, api_key))
    elapsed = time.time() - t0

    ok_results = [r for r in results if r["ok"]]
    fail_results = [r for r in results if not r["ok"]]

    print(f"\nDone in {elapsed:.1f}s | ok={len(ok_results)} | errors={len(fail_results)}")

    # Write to DB
    updated = 0
    for r in ok_results:
        cur.execute(
            "UPDATE companies SET website_summary=?, website_scraped_at=datetime('now'), website_scrape_source='exa' WHERE domain=? AND website_summary IS NULL",
            (r["summary"], r["domain"])
        )
        if cur.rowcount:
            updated += 1

    con.commit()

    print(f"DB updated: {updated} companies")

    if fail_results:
        print(f"\nErrors ({len(fail_results)}):")
        for r in fail_results[:10]:
            print(f"  {r['domain']}: {r['error']}")
        if len(fail_results) > 10:
            print(f"  ... and {len(fail_results)-10} more")

    con.close()


if __name__ == "__main__":
    main()

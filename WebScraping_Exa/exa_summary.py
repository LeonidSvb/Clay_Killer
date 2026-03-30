#!/usr/bin/env python3
"""
Exa Website Summary
Usage:
    py exa_summary.py --input leads.csv --output out.csv --limit 100
    py exa_summary.py --input leads.csv  (processes all pending, overwrites input)
"""

import asyncio
import aiohttp
import pandas as pd
import os
import time
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

EXA_API_KEY  = os.getenv("EXA_API_KEY")
URL_COL      = "Company Website"
SUMMARY_COL  = "Website Summary"
BATCH_SIZE   = 1    # batch size doesn't affect speed — Exa bottleneck is per-URL crawl
CONCURRENCY  = 50   # benchmark: 50 concur + maxAgeHours=24 → 7.6/s, 500 leads in ~66s
MAX_AGE_HOURS = 24  # use cache if fresher than 24h, livecrawl otherwise

SUMMARY_QUERY = (
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


async def fetch_batch(session, sem, batch, batch_idx, total):
    """Fetch summaries for a batch of URLs. Returns list of (idx, url, summary, ok)."""
    urls = [item["url"] for item in batch]
    async with sem:
        try:
            async with session.post(
                "https://api.exa.ai/contents",
                json={"ids": urls, "maxAgeHours": MAX_AGE_HOURS, "summary": {"query": SUMMARY_QUERY}},
                headers={"x-api-key": EXA_API_KEY},
                timeout=aiohttp.ClientTimeout(total=90),
            ) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    print(f"  [{batch_idx}/{total}] HTTP {resp.status}: {err[:100]}")
                    return [{"idx": item["idx"], "url": item["url"], "summary": "", "ok": False}
                            for item in batch]

                data = await resp.json()
                results = data.get("results", [])
                out = []
                for item, result in zip(batch, results):
                    summary = result.get("summary") or ""
                    out.append({"idx": item["idx"], "url": item["url"],
                                "summary": summary, "ok": bool(summary)})
                return out

        except asyncio.TimeoutError:
            print(f"  [{batch_idx}/{total}] TIMEOUT")
            return [{"idx": item["idx"], "url": item["url"], "summary": "", "ok": False}
                    for item in batch]
        except Exception as e:
            print(f"  [{batch_idx}/{total}] ERROR: {e}")
            return [{"idx": item["idx"], "url": item["url"], "summary": "", "ok": False}
                    for item in batch]


async def run(leads):
    batches = [leads[i:i + BATCH_SIZE] for i in range(0, len(leads), BATCH_SIZE)]
    total   = len(batches)
    sem     = asyncio.Semaphore(CONCURRENCY)
    results = []

    print(f"\n{len(leads)} leads | {total} batches x {BATCH_SIZE} | concurrency {CONCURRENCY}")

    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(fetch_batch(session, sem, b, i + 1, total))
            for i, b in enumerate(batches)
        ]
        done_count = 0
        t0 = time.time()
        for coro in asyncio.as_completed(tasks):
            batch_results = await coro
            results.extend(batch_results)
            done_count += len(batch_results)
            elapsed = time.time() - t0
            speed = done_count / elapsed if elapsed > 0 else 0
            eta = int((len(leads) - done_count) / speed) if speed > 0 else 0
            ok = sum(1 for r in results if r["ok"])
            print(f"  {done_count}/{len(leads)} | {speed:.1f}/sec | ETA {eta}s | ok {ok}", end="\r")

    print()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  required=True, help="Input CSV path")
    parser.add_argument("--output", default=None,  help="Output CSV path (default: overwrite input)")
    parser.add_argument("--limit",  type=int, default=0, help="Max leads to process (0 = all)")
    parser.add_argument("--reprocess", action="store_true",
                        help="Re-process rows that already have a summary")
    args = parser.parse_args()

    if not EXA_API_KEY:
        print("ERROR: EXA_API_KEY not set in .env")
        return

    df = pd.read_csv(args.input)
    print(f"Loaded {len(df)} rows from {args.input}")
    print(f"Columns: {df.columns.tolist()}")

    if SUMMARY_COL not in df.columns:
        df[SUMMARY_COL] = ""
        print(f"Added column '{SUMMARY_COL}'")

    # build pending list
    url_ok  = df[URL_COL].astype(str).str.strip().ne("")
    has_sum = df[SUMMARY_COL].astype(str).str.strip().ne("")

    if args.reprocess:
        mask = url_ok
    else:
        mask = url_ok & ~has_sum

    pending = [
        {"idx": i, "url": str(row[URL_COL]).strip()}
        for i, row in df[mask].iterrows()
    ]

    already_done = int(has_sum.sum())
    print(f"Total: {len(df)} | Already done: {already_done} | Pending: {len(pending)}")

    if not pending:
        print("Nothing to process.")
        return

    if args.limit > 0:
        pending = pending[:args.limit]
        print(f"Limit applied: processing {len(pending)}")

    t_start = time.time()
    results = asyncio.run(run(pending))
    t_exa   = time.time() - t_start

    ok  = sum(1 for r in results if r["ok"])
    err = len(results) - ok
    print(f"\nExa done: {ok} ok, {err} errors in {t_exa:.1f}s ({len(results)/t_exa:.1f}/sec)")

    for r in results:
        if r["ok"]:
            df.at[r["idx"], SUMMARY_COL] = r["summary"]

    output_path = args.output or args.input
    df.to_csv(output_path, index=False)
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()

"""
icebreakers_round_robin/run_extraction.py

Standalone extraction script.
Reads CSV, runs extraction prompt, saves JSONL.

Usage:
    py icebreakers_round_robin/run_extraction.py
    py icebreakers_round_robin/run_extraction.py --sample 50
    py icebreakers_round_robin/run_extraction.py --filter-multi-industry --runs 3
    py icebreakers_round_robin/run_extraction.py --input extractions/my.jsonl  (re-extract from existing)
"""

import asyncio
import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY  = os.getenv("OPENROUTER_API_KEY", "")
BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

MODELS = {
    "gpt4o_mini":   "openai/gpt-4o-mini",
    "gpt_oss_120b": "openai/gpt-oss-120b",
}

DEFAULT_CSV = r"C:\Users\79818\Downloads\_US+ recruit 10-100  - COPY#2 (2).csv"
THIS_DIR   = Path(__file__).parent
EXTRACT_DIR = THIS_DIR / "extractions"

_default_prompt = THIS_DIR / "extraction_prompt_final.txt"
if not _default_prompt.exists():
    _default_prompt = THIS_DIR / "extraction_prompt_v2.txt"
if not _default_prompt.exists():
    _default_prompt = THIS_DIR / "extraction_prompt_v1.txt"
EXTRACTION_PROMPT = _default_prompt.read_text(encoding="utf-8")


# ── helpers ────────────────────────────────────────────────────────────────────

def parse_json(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        result = json.loads(cleaned)
        return result if isinstance(result, dict) else {"raw": result}
    except Exception:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return {"raw": raw}


def build_prompt(row: dict) -> str:
    # supports both US and EU column naming conventions
    summary  = (row.get("Website Summary (100%)")
             or row.get("Website summary")
             or row.get("Website Summary") or "")
    desc     = (row.get("Company Short Description (68%)")
             or row.get("Company Short Description") or "")
    name     = (row.get("Company Name (100%)")
             or row.get("COMPANY NAME")
             or row.get("Company Name")
             or row.get("Clean Company") or "")
    website  = (row.get("Company Website (100%)")
             or row.get("Company Website")
             or row.get("domain") or "")
    keywords = (row.get("Company Keywords (100%)")
             or row.get("Keywords (100%)")
             or row.get("Keywords")
             or row.get("Company Keywords") or "")
    p = EXTRACTION_PROMPT
    p = p.replace("{{Website Summary}}", summary)
    p = p.replace("{{Company Short Description}}", desc)
    p = p.replace("{{Company Name}}", name)
    p = p.replace("{{Company Website}}", website)
    p = p.replace("{{Keywords}}", keywords)
    return p


async def call_llm(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    prompt: str,
    model_id: str,
    temperature: float = 0.1,
) -> tuple[dict, float]:
    t0 = time.monotonic()
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "provider": {"sort": "throughput"},
    }
    try:
        async with sem:
            resp = await client.post(BASE_URL, json=payload, timeout=90.0)
            elapsed = time.monotonic() - t0
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}: {resp.text[:120]}"}, elapsed
            data = resp.json()
            raw = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not isinstance(raw, str):
                raw = str(raw) if raw is not None else ""
            return parse_json(raw), elapsed
    except Exception as e:
        elapsed = time.monotonic() - t0
        return {"error": str(e)[:120]}, elapsed


async def extract_all(
    rows: list[dict],
    model_key: str,
    concurrency: int,
    run_id: int = 0,
    temperature: float = 0.1,
) -> list[dict]:
    model_id = MODELS[model_key]
    sem = asyncio.Semaphore(concurrency)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    async def one(i: int, row: dict) -> dict:
        result, elapsed = await call_llm(client, sem, build_prompt(row), model_id, temperature)
        return {
            "_idx":             i,
            "_run":             run_id,
            "_first_name":      row.get("FIRST NAME") or row.get("First Name", ""),
            "_last_name":       row.get("Last Name (99%)") or row.get("Last Name", ""),
            "_company_name":    row.get("COMPANY NAME") or row.get("Company Name", ""),
            "_company_website": row.get("Company Website (100%)") or row.get("Company Website", "") or row.get("domain", ""),
            "_country":         row.get("Country", "") or row.get("country", ""),
            "_email":           row.get("Email (100%)") or row.get("Email", ""),
            "_old_icebreaker":  row.get("PERSONALISATION", ""),
            "_t_extract_s":     round(elapsed, 2),
            "_model":           model_key,
            **result,
        }

    results = []
    done = 0
    t0 = time.time()

    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [asyncio.create_task(one(i, row)) for i, row in enumerate(rows)]
        for coro in asyncio.as_completed(tasks):
            r = await coro
            results.append(r)
            done += 1
            elapsed = time.time() - t0
            speed = done / elapsed if elapsed > 0 else 0
            print(f"  run={run_id} | {done}/{len(rows)} | {speed:.1f}/s", end="\r")

    print()
    results.sort(key=lambda x: x["_idx"])
    return results


# ── variance analysis ──────────────────────────────────────────────────────────

def print_stats(results: list[dict]):
    fields = [
        "primary_industry",
        "sub_industry",
        "primary_service",
        "client_profile",
        "company_type",
        "geography",
        "specificity",
        "extractability",
        "business_model",
    ]
    total = len(results)
    print(f"\n{'='*60}")
    print(f"EXTRACTION STATS — {total} rows")
    print(f"{'='*60}")
    for field in fields:
        counts = Counter(r.get(field) or "null" for r in results)
        if not counts:
            continue
        print(f"\n{field}:")
        for val, n in counts.most_common():
            bar = "#" * int(n / total * 30)
            print(f"  {val:<28} {n:>4}  {n/total*100:>5.1f}%  {bar}")
    errors = sum(1 for r in results if "error" in r)
    if errors:
        print(f"\nErrors: {errors}/{total}")
    print()


def print_variance_report(all_runs: list[list[dict]]):
    """Compare extraction results across multiple runs for the same rows."""
    n_rows = len(all_runs[0])
    n_runs = len(all_runs)

    print(f"\n{'='*60}")
    print(f"VARIANCE REPORT — {n_rows} rows × {n_runs} runs")
    print(f"{'='*60}\n")

    for i in range(n_rows):
        rows_across_runs = [run[i] for run in all_runs]
        name = rows_across_runs[0].get("_company_name", f"row_{i}")

        industries   = [r.get("primary_industry", "?") for r in rows_across_runs]
        sub_inds     = [r.get("sub_industry", "null") or "null" for r in rows_across_runs]
        services     = [r.get("primary_service", "?") for r in rows_across_runs]
        specificities= [r.get("specificity", "?") for r in rows_across_runs]

        ind_unique  = len(set(industries))
        sub_unique  = len(set(sub_inds))
        svc_unique  = len(set(services))

        # flag rows with variance
        has_variance = ind_unique > 1 or sub_unique > 1 or svc_unique > 1

        marker = " <<< VARIANCE" if has_variance else ""
        print(f"[{i+1}] {name}{marker}")
        print(f"  industry:    {industries}  (unique={ind_unique})")
        print(f"  sub_industry:{sub_inds}  (unique={sub_unique})")
        print(f"  service:     {services}  (unique={svc_unique})")
        print(f"  specificity: {specificities}")
        print()

    # summary
    stable   = sum(1 for i in range(n_rows)
                   if len(set(r.get("primary_industry","") for r in [run[i] for run in all_runs])) == 1
                   and len(set(r.get("sub_industry","") or "" for r in [run[i] for run in all_runs])) == 1)
    unstable = n_rows - stable
    print(f"Stable (same across all runs):   {stable}/{n_rows}")
    print(f"Unstable (variance in any field): {unstable}/{n_rows}")
    print()


# ── save ───────────────────────────────────────────────────────────────────────

def save_jsonl(results: list[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Saved: {path}  ({len(results)} records)")


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--sample",              type=int,   default=30)
    parser.add_argument("--concurrency",         type=int,   default=10)
    parser.add_argument("--model",               type=str,   default="gpt_oss_120b")
    parser.add_argument("--runs",                type=int,   default=1,
                        help="Run extraction N times and report variance")
    parser.add_argument("--temperature",         type=float, default=0.1)
    parser.add_argument("--input-csv",           type=str,   default=DEFAULT_CSV,
                        help="Path to input CSV file")
    parser.add_argument("--filter-multi-industry", action="store_true",
                        help="Only process rows classified as multi_industry in a previous extraction")
    parser.add_argument("--from-jsonl",          type=str,   default=None,
                        help="Load rows from existing JSONL instead of CSV (for re-extraction)")
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set")
        sys.exit(1)

    if args.model not in MODELS:
        print(f"Unknown model: {args.model}. Options: {list(MODELS.keys())}")
        sys.exit(1)

    # load rows
    if args.from_jsonl:
        src = Path(args.from_jsonl)
        print(f"Loading from JSONL: {src}")
        raw_rows = []
        with open(src, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    obj = json.loads(line)
                    # convert back to CSV-like row format
                    raw_rows.append({
                        "COMPANY NAME":              obj.get("_company_name", ""),
                        "Company Website (100%)":    obj.get("_company_website", ""),
                        "PERSONALISATION":           obj.get("_old_icebreaker", ""),
                        "Website Summary (100%)":    obj.get("_website_summary", ""),
                        "Company Short Description (68%)": obj.get("_company_desc", ""),
                    })
        all_rows = raw_rows
    else:
        with open(args.input_csv, encoding="utf-8") as f:
            all_rows = list(csv.DictReader(f))

    if args.filter_multi_industry:
        # load the most recent extraction to filter
        jsonl_files = sorted(EXTRACT_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not jsonl_files:
            print("No JSONL files found in extractions/ — cannot filter. Run without --filter-multi-industry first.")
            sys.exit(1)
        latest = jsonl_files[0]
        print(f"Filtering based on: {latest.name}")
        with open(latest, encoding="utf-8") as f:
            prev = [json.loads(l) for l in f if l.strip()]
        multi_indices = {r["_idx"] for r in prev if r.get("primary_industry") == "multi_industry"}
        sample = [all_rows[i] for i in sorted(multi_indices) if i < len(all_rows)]
        print(f"Filtered to {len(sample)} multi_industry rows (from {len(prev)} total)")
    else:
        sample = all_rows[:args.sample]

    print(f"\nModel: {args.model} ({MODELS[args.model]})")
    print(f"Rows: {len(sample)} | Runs: {args.runs} | Temperature: {args.temperature}")
    print(f"Total LLM calls: {len(sample) * args.runs}\n")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    all_runs = []

    for run_id in range(args.runs):
        if args.runs > 1:
            print(f"--- Run {run_id + 1}/{args.runs} ---")
        t0 = time.time()
        results = asyncio.run(extract_all(
            sample, args.model, args.concurrency,
            run_id=run_id, temperature=args.temperature
        ))
        elapsed = time.time() - t0

        errors = sum(1 for r in results if "error" in r)
        avg_t  = sum(r.get("_t_extract_s", 0) for r in results) / max(len(results), 1)
        print(f"Done in {elapsed:.1f}s | errors={errors} | avg={avg_t:.1f}s/row")

        suffix = f"_run{run_id}" if args.runs > 1 else ""
        out_path = EXTRACT_DIR / f"extraction_{ts}_{args.model}{suffix}.jsonl"
        save_jsonl(results, out_path)
        all_runs.append(results)
        print_stats(results)

    if args.runs > 1:
        print_variance_report(all_runs)


if __name__ == "__main__":
    main()

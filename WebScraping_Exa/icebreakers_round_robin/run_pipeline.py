"""
icebreakers_round_robin/run_pipeline.py

Two-prompt icebreaker pipeline: extraction + generation.
Saves extractions as JSONL (reusable), icebreakers as flat CSV.

Usage:
    py icebreakers_round_robin/run_pipeline.py
    py icebreakers_round_robin/run_pipeline.py --sample 50
    py icebreakers_round_robin/run_pipeline.py --model gpt_oss_120b
    py icebreakers_round_robin/run_pipeline.py --icebreaker-only extractions/extraction_20260404_120000_gpt_oss_120b.jsonl
"""

import asyncio
import argparse
import csv
import json
import os
import re
import sys
import time
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

INPUT_CSV  = r"C:\Users\79818\Downloads\_US+ recruit 10-100  - COPY#2 (2).csv"
THIS_DIR   = Path(__file__).parent
EXTRACT_DIR = THIS_DIR / "extractions"
IB_DIR      = THIS_DIR / "icebreakers"

EXTRACTION_PROMPT = (THIS_DIR / "extraction_prompt_v1.txt").read_text(encoding="utf-8")
ICEBREAKER_PROMPT = (THIS_DIR / "icebreaker_prompt_v1.txt").read_text(encoding="utf-8")


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


def build_extraction_prompt(row: dict) -> str:
    summary = row.get("Website Summary (100%)", "") or row.get("Website Summary", "")
    desc    = row.get("Company Short Description (68%)", "") or row.get("Company Short Description", "")
    name    = row.get("Company Name (100%)", "") or row.get("COMPANY NAME", "") or row.get("Company Name", "")
    website = row.get("Company Website (100%)", "") or row.get("Company Website", "")
    p = EXTRACTION_PROMPT
    p = p.replace("{{Website Summary}}", summary or "")
    p = p.replace("{{Company Short Description}}", desc or "")
    p = p.replace("{{Company Name}}", name or "")
    p = p.replace("{{Company Website}}", website or "")
    return p


def build_icebreaker_prompt(extraction: dict) -> str:
    return ICEBREAKER_PROMPT.replace(
        "{extraction_json}",
        json.dumps(extraction, ensure_ascii=False, indent=2)
    )


async def call_llm(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    prompt: str,
    model: str,
    temperature: float = 0.2,
) -> tuple[dict, float]:
    t0 = time.monotonic()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "provider": {"sort": "throughput"},
    }
    async with sem:
        resp = await client.post(BASE_URL, json=payload, timeout=90.0)
        elapsed = time.monotonic() - t0
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:120]}"}, elapsed
        raw = resp.json()["choices"][0]["message"]["content"]
        return parse_json(raw), elapsed


# ── step 1: extraction ─────────────────────────────────────────────────────────

async def run_extraction(
    rows: list[dict],
    model_key: str,
    concurrency: int,
) -> list[dict]:
    model_id = MODELS[model_key]
    sem = asyncio.Semaphore(concurrency)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    async def extract_one(i: int, row: dict) -> dict:
        prompt = build_extraction_prompt(row)
        ext, elapsed = await call_llm(client, sem, prompt, model_id, temperature=0.1)
        return {
            "_idx":            i,
            "_company_name":   row.get("COMPANY NAME") or row.get("Company Name", ""),
            "_company_website":row.get("Company Website (100%)") or row.get("Company Website", ""),
            "_old_icebreaker": row.get("PERSONALISATION", ""),
            "_t_extract_s":    round(elapsed, 2),
            "_model":          model_key,
            **ext,
        }

    results = [None] * len(rows)
    done = 0
    t0 = time.time()

    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [asyncio.create_task(extract_one(i, row)) for i, row in enumerate(rows)]
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results[result["_idx"]] = result
            done += 1
            elapsed = time.time() - t0
            speed = done / elapsed if elapsed > 0 else 0
            print(f"  extraction {done}/{len(rows)} | {speed:.1f}/s", end="\r")

    print()
    return results


def save_extractions(results: list[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Extractions saved: {path}")


def load_extractions(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.sort(key=lambda r: r.get("_idx", 0))
    return rows


# ── step 2: icebreaker ─────────────────────────────────────────────────────────

async def run_icebreakers(
    extractions: list[dict],
    model_key: str,
    concurrency: int,
) -> list[dict]:
    model_id = MODELS[model_key]
    sem = asyncio.Semaphore(concurrency)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    async def generate_one(ext: dict) -> dict:
        # strip internal meta keys before passing to icebreaker prompt
        clean_ext = {k: v for k, v in ext.items() if not k.startswith("_")}
        prompt = build_icebreaker_prompt(clean_ext)
        ib, elapsed = await call_llm(client, sem, prompt, model_id, temperature=0.4)
        return {
            "_idx":            ext.get("_idx", 0),
            "_company_name":   ext.get("_company_name", ""),
            "_company_website":ext.get("_company_website", ""),
            "_old_icebreaker": ext.get("_old_icebreaker", ""),
            "_t_icebr_s":      round(elapsed, 2),
            "_model":          model_key,
            **ib,
        }

    results = [None] * len(extractions)
    done = 0
    t0 = time.time()

    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [asyncio.create_task(generate_one(ext)) for ext in extractions]
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results[result["_idx"]] = result
            done += 1
            elapsed = time.time() - t0
            speed = done / elapsed if elapsed > 0 else 0
            print(f"  icebreakers {done}/{len(extractions)} | {speed:.1f}/s", end="\r")

    print()
    return results


def save_icebreakers(icebreakers: list[dict], extractions: list[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    ext_by_idx = {e.get("_idx", i): e for i, e in enumerate(extractions)}

    fields = [
        "company_name", "company_website", "old_icebreaker",
        "new_icebreaker", "icp", "pain",
        "service", "secondary_services", "business_model",
        "industry", "secondary_industries", "sub_industry",
        "specificity", "company_type", "company_stage",
        "geography", "confidence", "reasoning",
        "t_extract_s", "t_icebr_s", "model",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for ib in icebreakers:
            idx = ib.get("_idx", 0)
            ext = ext_by_idx.get(idx, {})
            sec_svc = ext.get("secondary_services", [])
            sec_ind = ext.get("secondary_industries", [])
            writer.writerow({
                "company_name":         ib.get("_company_name", ""),
                "company_website":      ib.get("_company_website", ""),
                "old_icebreaker":       ib.get("_old_icebreaker", ""),
                "new_icebreaker":       ib.get("icebreaker", ib.get("raw", "ERROR")),
                "icp":                  ib.get("icp", ""),
                "pain":                 ib.get("pain", ""),
                "service":              ext.get("primary_service", ""),
                "secondary_services":   ", ".join(sec_svc) if isinstance(sec_svc, list) else str(sec_svc),
                "business_model":       ext.get("business_model", ""),
                "industry":             ext.get("primary_industry", ""),
                "secondary_industries": ", ".join(sec_ind) if isinstance(sec_ind, list) else str(sec_ind),
                "sub_industry":         ext.get("sub_industry", ""),
                "specificity":          ext.get("specificity", ""),
                "company_type":         ext.get("company_type", ""),
                "company_stage":        ext.get("company_stage", ""),
                "geography":            ext.get("geography", ""),
                "confidence":           ext.get("confidence", ""),
                "reasoning":            ext.get("reasoning", ""),
                "t_extract_s":          ext.get("_t_extract_s", ""),
                "t_icebr_s":            ib.get("_t_icebr_s", ""),
                "model":                ib.get("_model", ""),
            })

    print(f"Icebreakers saved: {path}")


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--sample",          type=int, default=30)
    parser.add_argument("--concurrency",     type=int, default=8)
    parser.add_argument("--model",           type=str, default="gpt_oss_120b",
                        help="gpt4o_mini | gpt_oss_120b | both")
    parser.add_argument("--icebreaker-only", type=str, default=None,
                        help="Path to existing .jsonl — skip extraction, only generate icebreakers")
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set")
        sys.exit(1)

    if args.model == "both":
        model_keys = list(MODELS.keys())
    elif args.model in MODELS:
        model_keys = [args.model]
    else:
        print(f"Unknown model: {args.model}. Options: {list(MODELS.keys())} | both")
        sys.exit(1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── mode: icebreaker-only from existing extraction ──────────────────────────
    if args.icebreaker_only:
        jsonl_path = Path(args.icebreaker_only)
        print(f"\nLoading extractions from: {jsonl_path}")
        extractions = load_extractions(jsonl_path)
        print(f"Loaded {len(extractions)} records\n")

        for mk in model_keys:
            print(f"Generating icebreakers | model={mk}")
            icebreakers = asyncio.run(run_icebreakers(extractions, mk, args.concurrency))
            ib_path = IB_DIR / f"icebreakers_{ts}_{mk}.csv"
            save_icebreakers(icebreakers, extractions, ib_path)
        return

    # ── mode: full pipeline ─────────────────────────────────────────────────────
    with open(INPUT_CSV, encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    sample = all_rows[:args.sample]
    print(f"\nInput: {len(sample)} rows (of {len(all_rows)} total)")

    for mk in model_keys:
        print(f"\n{'='*50}")
        print(f"Model: {mk} ({MODELS[mk]})")
        print(f"{'='*50}")

        # step 1: extraction
        print(f"Step 1: Extraction...")
        t0 = time.time()
        extractions = asyncio.run(run_extraction(sample, mk, args.concurrency))
        t1 = time.time() - t0
        print(f"Done in {t1:.1f}s")

        ext_path = EXTRACT_DIR / f"extraction_{ts}_{mk}.jsonl"
        save_extractions(extractions, ext_path)

        errors = sum(1 for e in extractions if "error" in e)
        print(f"Errors: {errors}/{len(extractions)}")

        # step 2: icebreakers
        print(f"\nStep 2: Icebreaker generation...")
        t0 = time.time()
        icebreakers = asyncio.run(run_icebreakers(extractions, mk, args.concurrency))
        t2 = time.time() - t0
        print(f"Done in {t2:.1f}s")

        ib_path = IB_DIR / f"icebreakers_{ts}_{mk}.csv"
        save_icebreakers(icebreakers, extractions, ib_path)

        print(f"\nTotal time: {t1+t2:.1f}s | {len(sample)/(t1+t2)*60:.0f} leads/min")


if __name__ == "__main__":
    main()

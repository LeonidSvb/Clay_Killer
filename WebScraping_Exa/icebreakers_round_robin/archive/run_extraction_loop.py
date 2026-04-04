"""
icebreakers_round_robin/run_extraction_loop.py

Agentic prompt optimization loop for extraction quality.
Two agents:
  - QA Agent:          reads raw lead data, sets ground truth, judges what's detectable
  - Prompt Engineer:   analyzes failures, rewrites extraction prompt

Loop runs until accuracy >= TARGET_ACCURACY or MAX_ITERATIONS reached.
All iterations saved to loop_results/

Usage:
    py icebreakers_round_robin/run_extraction_loop.py
    py icebreakers_round_robin/run_extraction_loop.py --target 0.90 --max-iter 8
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

API_KEY   = os.getenv("OPENROUTER_API_KEY", "")
BASE_URL  = "https://openrouter.ai/api/v1/chat/completions"
MODEL_ID  = "openai/gpt-oss-120b"

INPUT_CSV    = r"C:\Users\79818\Downloads\_US+ recruit 10-100  - COPY#2 (2).csv"
THIS_DIR     = Path(__file__).parent
LOOP_DIR     = THIS_DIR / "loop_results"
EXTRACT_DIR  = THIS_DIR / "extractions"

TARGET_ACCURACY = 0.95
MAX_ITERATIONS  = 7
CONCURRENCY     = 10

VALID_INDUSTRIES = {
    "healthcare", "information_technology", "finance", "manufacturing",
    "construction", "logistics", "retail", "other", "multi_industry", "unknown"
}

VALID_SUB_INDUSTRIES = {
    "hospitals", "pharma", "biotech", "medical_devices", "private_clinics",
    "home_care", "dental", "mental_health", "health_tech",
    "saas", "cybersecurity", "ai_ml", "enterprise_software", "dev_agencies",
    "it_services", "ecommerce_tech", "telecom", "gaming",
    "banking", "investment_banking", "private_equity", "venture_capital",
    "accounting", "insurance", "wealth_management", "fintech", "real_estate_finance",
    "automotive", "aerospace_defense", "food_beverage", "industrial_equipment",
    "chemicals", "electronics_manufacturing", "packaging", "textile_apparel",
    "commercial_construction", "residential_construction", "civil_infrastructure",
    "specialty_trades", "real_estate_development",
    "warehousing_distribution", "transportation_freight", "supply_chain_management",
    "last_mile_delivery", "maritime_aviation",
    "ecommerce", "consumer_goods", "grocery_food_retail", "fashion_apparel", "luxury_retail",
    "legal", "education", "hospitality", "energy_oil_gas", "renewables",
    "real_estate_services", "nonprofit", "government", "virtual_assistants",
}

# ── prompts ────────────────────────────────────────────────────────────────────

QA_AGENT_PROMPT = """You are a strict QA analyst for a recruiting/staffing data pipeline.

Your job: read the raw company data below and determine whether the PRIMARY INDUSTRY this recruiting firm serves can be reasonably determined by a smart human analyst.

Think carefully:
- Look for explicit mentions: "we serve healthcare clients", "our candidates work in finance"
- Look for implicit signals: role types recruited, client logos, domain terminology, case study language
- Look for niche positioning: company name, tagline, specialization claims

Then decide:
1. Is the industry DETECTABLE? (yes = a reasonable analyst would agree on the answer)
2. If yes — what is the correct primary_industry and sub_industry from our taxonomy?

Allowed primary_industry values:
healthcare | information_technology | finance | manufacturing | construction | logistics | retail | other | multi_industry

Use multi_industry ONLY if the firm genuinely serves 3+ unrelated industries with no dominant one.

Allowed sub_industry values:
healthcare: hospitals | pharma | biotech | medical_devices | private_clinics | home_care | dental | mental_health | health_tech
information_technology: saas | cybersecurity | ai_ml | enterprise_software | dev_agencies | it_services | ecommerce_tech | telecom | gaming
finance: banking | investment_banking | private_equity | venture_capital | accounting | insurance | wealth_management | fintech | real_estate_finance
manufacturing: automotive | aerospace_defense | food_beverage | industrial_equipment | chemicals | electronics_manufacturing | packaging | textile_apparel
construction: commercial_construction | residential_construction | civil_infrastructure | specialty_trades | real_estate_development
logistics: warehousing_distribution | transportation_freight | supply_chain_management | last_mile_delivery | maritime_aviation
retail: ecommerce | consumer_goods | grocery_food_retail | fashion_apparel | luxury_retail
other: legal | education | hospitality | energy_oil_gas | renewables | real_estate_services | nonprofit | government | virtual_assistants

Return ONLY valid JSON:
{{
  "detectable": true/false,
  "detection_reason": "why this is or is not detectable — cite specific signals from the text",
  "correct_primary_industry": "...",
  "correct_sub_industry": "... or null",
  "correct_secondary_industries": [],
  "ground_truth_confidence": 1-10
}}

Company data:
Company name: {company_name}
Website: {company_website}
Website Summary: {website_summary}
Company Description: {company_desc}
"""


PROMPT_ENGINEER_PROMPT = """You are a senior prompt engineer specializing in information extraction from business text.

You are improving an extraction prompt that classifies recruiting/staffing agencies by industry and sub-industry.

## CURRENT PROMPT:
{current_prompt}

## FAILURE CASES (where the prompt got it wrong but the answer was detectable):
{failure_cases}

## INSTRUCTIONS:
1. Analyze WHY the current prompt failed for each case
2. Identify PATTERNS in the failures (not just individual fixes)
3. Rewrite the relevant sections of the prompt to fix these patterns
4. Do NOT break sections that are currently working well
5. Do NOT make the prompt overly verbose — it should remain precise and actionable
6. The key issue is usually: the prompt is too conservative, defaulting to multi_industry when signals exist

Return ONLY valid JSON:
{{
  "failure_analysis": "2-4 sentences describing the root cause pattern across all failures",
  "changes_made": ["change 1", "change 2", "change 3"],
  "new_prompt": "the complete rewritten extraction prompt — preserve all working sections, only fix what's broken"
}}
"""


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
    return {"raw": raw, "parse_error": True}


def industry_match(predicted: str, ground_truth: str) -> bool:
    if not predicted or not ground_truth:
        return False
    return predicted.strip().lower() == ground_truth.strip().lower()


def sub_industry_match(predicted: str, ground_truth: str) -> bool:
    if not ground_truth:
        return True   # no sub_industry required → pass
    if not predicted:
        return False
    return predicted.strip().lower() == ground_truth.strip().lower()


def score_result(extraction: dict, gt: dict) -> dict:
    ind_ok = industry_match(extraction.get("primary_industry", ""), gt.get("correct_primary_industry", ""))
    sub_ok = sub_industry_match(extraction.get("sub_industry") or "", gt.get("correct_sub_industry") or "")
    return {
        "industry_correct": ind_ok,
        "sub_industry_correct": sub_ok,
        "fully_correct": ind_ok and sub_ok,
    }


async def call_llm(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    prompt: str,
    temperature: float = 0.1,
) -> dict:
    payload = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "provider": {"sort": "throughput"},
    }
    async with sem:
        resp = await client.post(BASE_URL, json=payload, timeout=120.0)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:120]}"}
        raw = resp.json()["choices"][0]["message"]["content"]
        return parse_json(raw)


# ── qa agent: establish ground truth ─────────────────────────────────────────

async def run_qa_agent(rows: list[dict], concurrency: int) -> list[dict]:
    print("\n[QA Agent] Establishing ground truth for all cases...")
    sem = asyncio.Semaphore(concurrency)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    async def evaluate_one(i: int, row: dict) -> dict:
        prompt = QA_AGENT_PROMPT.format(
            company_name    = row.get("COMPANY NAME") or row.get("Company Name", ""),
            company_website = row.get("Company Website (100%)") or row.get("Company Website", ""),
            website_summary = row.get("Website Summary (100%)", "") or "",
            company_desc    = row.get("Company Short Description (68%)", "") or "",
        )
        result = await call_llm(client, sem, prompt, temperature=0.1)
        return {
            "_idx":           i,
            "_company_name":  row.get("COMPANY NAME") or row.get("Company Name", ""),
            "_company_website": row.get("Company Website (100%)") or row.get("Company Website", ""),
            **result
        }

    results = [None] * len(rows)
    done = 0
    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [asyncio.create_task(evaluate_one(i, row)) for i, row in enumerate(rows)]
        for coro in asyncio.as_completed(tasks):
            r = await coro
            results[r["_idx"]] = r
            done += 1
            print(f"  QA: {done}/{len(rows)}", end="\r")

    print()
    return results


# ── extraction runner ─────────────────────────────────────────────────────────

def build_extraction_prompt(row: dict, prompt_template: str) -> str:
    p = prompt_template
    p = p.replace("{{Website Summary}}", row.get("Website Summary (100%)", "") or "")
    p = p.replace("{{Company Short Description}}", row.get("Company Short Description (68%)", "") or "")
    p = p.replace("{{Company Name}}", row.get("COMPANY NAME") or row.get("Company Name", "") or "")
    p = p.replace("{{Company Website}}", row.get("Company Website (100%)") or row.get("Company Website", "") or "")
    return p


async def run_extraction(rows: list[dict], prompt_template: str, concurrency: int) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    async def extract_one(i: int, row: dict) -> dict:
        prompt = build_extraction_prompt(row, prompt_template)
        result = await call_llm(client, sem, prompt, temperature=0.1)
        return {"_idx": i, **result}

    results = [None] * len(rows)
    done = 0
    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [asyncio.create_task(extract_one(i, row)) for i, row in enumerate(rows)]
        for coro in asyncio.as_completed(tasks):
            r = await coro
            results[r["_idx"]] = r
            done += 1
            print(f"  Extraction: {done}/{len(rows)}", end="\r")

    print()
    return results


# ── accuracy calculation ───────────────────────────────────────────────────────

def calculate_accuracy(
    extractions: list[dict],
    ground_truths: list[dict],
) -> dict:
    detectable_cases = [gt for gt in ground_truths if gt.get("detectable") is True]
    if not detectable_cases:
        return {"accuracy": 1.0, "detectable_count": 0, "correct": 0, "failures": []}

    correct = 0
    failures = []
    industry_correct = 0
    sub_correct = 0

    for gt in detectable_cases:
        idx = gt["_idx"]
        ext = next((e for e in extractions if e.get("_idx") == idx), {})
        scores = score_result(ext, gt)

        if scores["fully_correct"]:
            correct += 1
        else:
            failures.append({
                "idx":                   idx,
                "company_name":          gt.get("_company_name", ""),
                "ground_truth_industry": gt.get("correct_primary_industry", ""),
                "ground_truth_sub":      gt.get("correct_sub_industry", ""),
                "got_industry":          ext.get("primary_industry", "MISSING"),
                "got_sub":               ext.get("sub_industry", "MISSING") or "null",
                "detection_reason":      gt.get("detection_reason", ""),
                "extracted_reasoning":   ext.get("reasoning", ""),
                "extracted_signals":     ext.get("detected_signals", ""),
                "industry_correct":      scores["industry_correct"],
                "sub_industry_correct":  scores["sub_industry_correct"],
            })

        if scores["industry_correct"]:
            industry_correct += 1
        if scores["sub_industry_correct"]:
            sub_correct += 1

    total = len(detectable_cases)
    return {
        "accuracy":          round(correct / total, 3),
        "industry_accuracy": round(industry_correct / total, 3),
        "sub_accuracy":      round(sub_correct / total, 3),
        "detectable_count":  total,
        "correct":           correct,
        "failures":          failures,
    }


# ── prompt engineer ────────────────────────────────────────────────────────────

async def run_prompt_engineer(
    failures: list[dict],
    current_prompt: str,
    concurrency: int,
) -> dict:
    print("\n[Prompt Engineer] Analyzing failures and rewriting prompt...")

    failure_summary = []
    for f in failures:
        failure_summary.append({
            "company":          f["company_name"],
            "should_be":        f["ground_truth_industry"] + ("/" + f["ground_truth_sub"] if f["ground_truth_sub"] else ""),
            "got":              f["got_industry"] + ("/" + f["got_sub"] if f["got_sub"] and f["got_sub"] != "null" else ""),
            "detectable_signal":f["detection_reason"],
            "what_prompt_said": f["extracted_reasoning"][:200] if f["extracted_reasoning"] else "",
        })

    prompt = PROMPT_ENGINEER_PROMPT.format(
        current_prompt = current_prompt,
        failure_cases  = json.dumps(failure_summary, indent=2, ensure_ascii=False),
    )

    sem = asyncio.Semaphore(1)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(headers=headers) as client:
        result = await call_llm(client, sem, prompt, temperature=0.2)

    return result


# ── main loop ─────────────────────────────────────────────────────────────────

def main():
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--target",   type=float, default=TARGET_ACCURACY)
    parser.add_argument("--max-iter", type=int,   default=MAX_ITERATIONS)
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY)
    parser.add_argument("--sample",   type=int,   default=None,
                        help="Limit rows (default: all multi_industry from last extraction)")
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set")
        sys.exit(1)

    # load multi_industry rows from last extraction
    jsonl_files = sorted(EXTRACT_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not jsonl_files:
        print("No JSONL in extractions/ — run run_extraction.py first")
        sys.exit(1)

    latest_jsonl = jsonl_files[0]
    print(f"Base extraction: {latest_jsonl.name}")
    with open(latest_jsonl, encoding="utf-8") as f:
        prev_extraction = [json.loads(l) for l in f if l.strip()]

    multi_indices = sorted({r["_idx"] for r in prev_extraction if r.get("primary_industry") == "multi_industry"})
    print(f"Multi-industry rows found: {len(multi_indices)}")

    # load original CSV
    with open(INPUT_CSV, encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    target_rows = [all_rows[i] for i in multi_indices if i < len(all_rows)]
    if args.sample:
        target_rows = target_rows[:args.sample]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = LOOP_DIR / f"run_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # ── step 1: QA agent sets ground truth (runs once) ──────────────────────────
    ground_truths = asyncio.run(run_qa_agent(target_rows, args.concurrency))
    detectable = [gt for gt in ground_truths if gt.get("detectable") is True]
    not_detectable = [gt for gt in ground_truths if gt.get("detectable") is False]

    gt_path = run_dir / "ground_truth.json"
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump(ground_truths, f, indent=2, ensure_ascii=False)

    print(f"\nGround truth:")
    print(f"  Detectable:     {len(detectable)}/{len(ground_truths)}")
    print(f"  Not detectable: {len(not_detectable)}/{len(ground_truths)}")
    print()
    for gt in detectable:
        print(f"  [{gt['_idx']}] {gt['_company_name']}: {gt.get('correct_primary_industry','?')} / {gt.get('correct_sub_industry','null')}")
        print(f"       Signal: {gt.get('detection_reason','')[:100]}")
    print()
    for gt in not_detectable:
        print(f"  [{gt['_idx']}] {gt['_company_name']}: NOT DETECTABLE — {gt.get('detection_reason','')[:80]}")

    if not detectable:
        print("\nAll multi_industry cases are truly not detectable. Extraction is already optimal.")
        sys.exit(0)

    # ── step 2: load starting prompt ────────────────────────────────────────────
    current_prompt_path = THIS_DIR / "extraction_prompt_v2.txt"
    if not current_prompt_path.exists():
        current_prompt_path = THIS_DIR / "extraction_prompt_v1.txt"
    current_prompt = current_prompt_path.read_text(encoding="utf-8")
    print(f"Starting prompt: {current_prompt_path.name}\n")

    history = []

    # ── main loop ────────────────────────────────────────────────────────────────
    for iteration in range(1, args.max_iter + 1):
        print(f"{'='*60}")
        print(f"ITERATION {iteration}/{args.max_iter}")
        print(f"{'='*60}")

        iter_dir = run_dir / f"iter_{iteration:02d}"
        iter_dir.mkdir(parents=True, exist_ok=True)

        # save current prompt
        (iter_dir / "prompt.txt").write_text(current_prompt, encoding="utf-8")

        # run extraction
        t0 = time.time()
        extractions = asyncio.run(run_extraction(target_rows, current_prompt, args.concurrency))
        elapsed = time.time() - t0
        print(f"  Done in {elapsed:.1f}s")

        (iter_dir / "extractions.json").write_text(
            json.dumps(extractions, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # calculate accuracy
        accuracy_report = calculate_accuracy(extractions, ground_truths)
        accuracy = accuracy_report["accuracy"]

        (iter_dir / "accuracy.json").write_text(
            json.dumps(accuracy_report, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        print(f"\n  Accuracy: {accuracy*100:.1f}% ({accuracy_report['correct']}/{accuracy_report['detectable_count']} detectable cases)")
        print(f"  Industry: {accuracy_report['industry_accuracy']*100:.1f}%  |  Sub-industry: {accuracy_report['sub_accuracy']*100:.1f}%")

        if accuracy_report["failures"]:
            print(f"\n  Failures ({len(accuracy_report['failures'])}):")
            for f in accuracy_report["failures"]:
                print(f"    [{f['idx']}] {f['company_name']}: expected={f['ground_truth_industry']}/{f['ground_truth_sub']} | got={f['got_industry']}/{f['got_sub']}")
                print(f"         Signal was: {f['detection_reason'][:90]}")

        history.append({
            "iteration": iteration,
            "accuracy":  accuracy,
            "failures":  len(accuracy_report["failures"]),
        })

        if accuracy >= args.target:
            print(f"\nTarget {args.target*100:.0f}% reached! Stopping.")
            break

        if iteration == args.max_iter:
            print(f"\nMax iterations reached.")
            break

        # run prompt engineer
        engineer_result = asyncio.run(run_prompt_engineer(
            accuracy_report["failures"], current_prompt, args.concurrency
        ))

        if "parse_error" in engineer_result or "new_prompt" not in engineer_result:
            print(f"  Prompt engineer returned invalid response. Stopping.")
            break

        print(f"\n  Prompt Engineer analysis: {engineer_result.get('failure_analysis','')[:200]}")
        print(f"  Changes: {engineer_result.get('changes_made', [])}")

        (iter_dir / "engineer_analysis.json").write_text(
            json.dumps(engineer_result, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        current_prompt = engineer_result["new_prompt"]
        print()

    # ── save final prompt ────────────────────────────────────────────────────────
    final_prompt_path = run_dir / "final_prompt.txt"
    final_prompt_path.write_text(current_prompt, encoding="utf-8")

    # also save as next version in main folder
    existing_versions = sorted(THIS_DIR.glob("extraction_prompt_v*.txt"))
    next_version = len(existing_versions) + 1
    versioned_path = THIS_DIR / f"extraction_prompt_v{next_version}.txt"
    versioned_path.write_text(current_prompt, encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"LOOP COMPLETE")
    print(f"{'='*60}")
    print(f"Results saved: {run_dir}")
    print(f"Final prompt:  {versioned_path.name}")
    print(f"\nAccuracy history:")
    for h in history:
        bar = "#" * int(h["accuracy"] * 20)
        print(f"  Iter {h['iteration']}: {h['accuracy']*100:5.1f}%  [{bar:<20}]  failures={h['failures']}")


if __name__ == "__main__":
    main()

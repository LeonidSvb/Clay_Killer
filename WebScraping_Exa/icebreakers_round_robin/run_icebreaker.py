"""
icebreakers_round_robin/run_icebreaker.py

Reads extraction JSONL + matrix.json + copy template → generates full emails → saves CSV.

Usage:
    py icebreakers_round_robin/run_icebreaker.py --variant A
    py icebreakers_round_robin/run_icebreaker.py --variant B --jsonl extractions/my.jsonl
    py icebreakers_round_robin/run_icebreaker.py --variant A --sample 25
    py icebreakers_round_robin/run_icebreaker.py --variant E --use-consequence
"""

import asyncio
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.stdout.reconfigure(encoding="utf-8")

API_KEY  = os.getenv("OPENROUTER_API_KEY", "")
BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_ID = "openai/gpt-oss-120b"

THIS_DIR    = Path(__file__).parent
MATRIX_PATH = THIS_DIR / "matrix.json"
PROMPT_PATH = THIS_DIR / "icebreaker_prompt_final.txt"
COPY_DIR    = THIS_DIR / "copy"
EXTRACT_DIR = THIS_DIR / "extractions"
OUTPUT_DIR  = THIS_DIR / "icebreakers"

MATRIX            = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
ICEBREAKER_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")


# ── load copy template ─────────────────────────────────────────────────────────

def load_copy_template(variant: str) -> tuple[str, dict]:
    """Load copy template, return (body, meta) where body has {{custom_personalisation}}."""
    path = COPY_DIR / f"variant_{variant}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Copy variant not found: {path}")

    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n")

    meta = {}
    body_lines = []
    in_body = False

    for line in lines:
        if line.strip() == "---":
            in_body = True
            continue
        if not in_body:
            if ":" in line and not line.startswith(" "):
                k, _, v = line.partition(":")
                meta[k.strip().upper()] = v.strip()
        else:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()
    return body, meta


# ── matrix lookup ──────────────────────────────────────────────────────────────

def matrix_lookup(service: str, sub_industry: str) -> dict:
    key = f"{service}__{sub_industry}"
    if key in MATRIX:
        return MATRIX[key]

    for k, v in MATRIX.items():
        if k.startswith("_"):
            continue
        if k.endswith(f"__{sub_industry}"):
            return v

    fb = MATRIX.get("_fallbacks", {})
    svc_fallback = f"{service}__generic"
    if svc_fallback in fb:
        return fb[svc_fallback]

    return fb.get("generic__generic", {
        "dreamICP": "HR and ops leaders at growing companies",
        "pain": "finding the right people is taking longer than the business can afford",
        "pain_consequence": "every open seat is costing more in lost output than the hire itself would",
    })


# ── pain selector ──────────────────────────────────────────────────────────────

def select_pain(entry: dict, use_alt: bool, use_consequence: bool) -> str:
    if use_consequence:
        return entry.get("pain_consequence") or entry.get("pain", "")
    if use_alt:
        return entry.get("pain_alt") or entry.get("pain", "")
    return entry.get("pain", "")


# ── prompt builder ─────────────────────────────────────────────────────────────

def build_icebreaker_prompt(row: dict, matrix_entry: dict, pain: str, variant_meta: dict) -> str:
    p = ICEBREAKER_PROMPT
    p = p.replace("{{dreamICP_base}}",    matrix_entry.get("dreamICP", ""))
    p = p.replace("{{pain_base}}",        pain)
    p = p.replace("{{company_name}}",     row.get("_company_name", ""))
    p = p.replace("{{country}}",          row.get("_country", ""))
    p = p.replace("{{client_profile}}",   row.get("client_profile", "unknown"))
    p = p.replace("{{detected_signals}}", (row.get("detected_signals", "") or "")[:300])

    # lowercase instruction based on variant
    if variant_meta.get("HYPOTHESIS", "").startswith("full lowercase"):
        p += "\n\nIMPORTANT: output must be fully lowercase — no capital letters anywhere."

    return p


# ── assemble full email ────────────────────────────────────────────────────────

def assemble_email(
    template: str,
    personalisation: str,
    first_name: str,
    sender_name: str,
    variant_meta: dict,
) -> str:
    lowercase = variant_meta.get("HYPOTHESIS", "").startswith("full lowercase")

    display_first = first_name if first_name else "there"
    if lowercase:
        display_first = display_first.lower()
        personalisation = personalisation.lower()

    email = template
    email = email.replace("{{first_name}}", display_first)
    email = email.replace("{{custom_personalisation}}", personalisation)
    email = email.replace("{{sender_first_name}}", sender_name)
    return email


# ── LLM call ──────────────────────────────────────────────────────────────────

async def call_llm(client, sem, prompt: str) -> tuple[str, float]:
    t0 = time.monotonic()
    payload = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "provider": {"sort": "throughput"},
    }
    try:
        async with sem:
            resp = await client.post(BASE_URL, json=payload, timeout=60.0)
            elapsed = time.monotonic() - t0
            if resp.status_code != 200:
                return f"ERROR: HTTP {resp.status_code}", elapsed
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            return (content or "").strip(), elapsed
    except Exception as e:
        return f"ERROR: {e}", time.monotonic() - t0


# ── generate all ──────────────────────────────────────────────────────────────

async def generate_all(
    rows: list[dict],
    concurrency: int,
    use_alt: bool,
    use_consequence: bool,
    copy_template: str,
    variant_meta: dict,
    sender_name: str,
) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    results = []
    done = 0
    t0 = time.time()

    async def one(row: dict) -> dict:
        svc   = row.get("primary_service") or "unknown"
        sub   = row.get("sub_industry") or "null"
        entry = matrix_lookup(svc, sub)
        pain  = select_pain(entry, use_alt, use_consequence)

        prompt      = build_icebreaker_prompt(row, entry, pain, variant_meta)
        custom, elapsed = await call_llm(client, sem, prompt)

        first_name = row.get("_first_name", "") or ""
        full_email = assemble_email(copy_template, custom, first_name, sender_name, variant_meta)

        return {
            "_idx":               row.get("_idx"),
            "first_name":         first_name,
            "_company_name":      row.get("_company_name", ""),
            "_company_website":   row.get("_company_website", ""),
            "_country":           row.get("_country", ""),
            "primary_service":    svc,
            "sub_industry":       sub,
            "client_profile":     row.get("client_profile", ""),
            "matrix_key":         f"{svc}__{sub}",
            "matrix_pain_used":   pain,
            "custom_personalisation": custom,
            "full_email":         full_email,
            "_t_s":               round(elapsed, 2),
        }

    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [asyncio.create_task(one(row)) for row in rows]
        for coro in asyncio.as_completed(tasks):
            r = await coro
            results.append(r)
            done += 1
            speed = done / max(time.time() - t0, 0.1)
            print(f"  {done}/{len(rows)} | {speed:.1f}/s", end="\r")

    print()
    results.sort(key=lambda x: (x["_idx"] or 0))
    return results


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant",        type=str, default="A", choices=["A","B","C","D","E"],
                        help="Copy variant (A-E)")
    parser.add_argument("--jsonl",          type=str, default=None)
    parser.add_argument("--concurrency",    type=int, default=40)
    parser.add_argument("--use-alt",        action="store_true",
                        help="Use pain_alt from matrix")
    parser.add_argument("--use-consequence", action="store_true",
                        help="Use pain_consequence from matrix (for Variant E)")
    parser.add_argument("--sample",         type=int, default=None)
    parser.add_argument("--sender",         type=str, default="Alex",
                        help="Sender first name for email signature")
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set")
        sys.exit(1)

    copy_template, variant_meta = load_copy_template(args.variant)

    # auto-select pain field from variant meta
    pain_field = variant_meta.get("PAIN_FIELD", "pain")
    use_alt         = args.use_alt         or (pain_field == "pain_alt")
    use_consequence = args.use_consequence or (pain_field == "pain_consequence")

    # load JSONL
    if args.jsonl:
        jsonl_path = Path(args.jsonl)
    else:
        files = sorted(EXTRACT_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            print("No JSONL files found in extractions/")
            sys.exit(1)
        jsonl_path = files[0]
        print(f"Using latest extraction: {jsonl_path.name}")

    rows = [json.loads(l) for l in open(jsonl_path, encoding="utf-8") if l.strip()]
    if args.sample:
        rows = rows[:args.sample]

    print(f"\nVariant: {args.variant} | Pain: {pain_field} | Rows: {len(rows)} | Sender: {args.sender}\n")

    results = asyncio.run(generate_all(
        rows, args.concurrency, use_alt, use_consequence,
        copy_template, variant_meta, args.sender,
    ))

    # save CSV
    OUTPUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"emails_{ts}_variant{args.variant}.csv"

    fields = [
        "_idx", "first_name", "_company_name", "_company_website", "_country",
        "primary_service", "sub_industry", "client_profile",
        "matrix_key", "matrix_pain_used",
        "custom_personalisation", "full_email",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    errors = sum(1 for r in results if str(r.get("custom_personalisation", "")).startswith("ERROR"))
    print(f"Saved: {out_path}")
    print(f"Total: {len(results)} | Errors: {errors}")

    # preview
    print("\n--- SAMPLE EMAILS (first 3) ---")
    for r in results[:3]:
        print(f"\n{'='*60}")
        print(f"[{r['_idx']}] {r['_company_name']} | {r['_country']} | {r['matrix_key']}")
        print(f"{'='*60}")
        print(r["full_email"])


if __name__ == "__main__":
    main()

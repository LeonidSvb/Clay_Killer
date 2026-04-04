"""
icebreakers_round_robin/run_canada.py

Canada pipeline: Exa fetch → extraction → icebreaker → campaign CSV.
Outputs a/b test file with email_a_dealflow + email_b_lowercase columns.
Compatible with US campaign structure for Plusvibe merge.

Usage:
    py icebreakers_round_robin/run_canada.py
    py icebreakers_round_robin/run_canada.py --sample 20
    py icebreakers_round_robin/run_canada.py --skip-exa (use Short Description only)
    py icebreakers_round_robin/run_canada.py --exa-only  (fetch + extract only, no icebreakers)
    py icebreakers_round_robin/run_canada.py --from-jsonl icebreakers_round_robin/extractions/canada_extraction_xxx.jsonl
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

import aiohttp
import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.stdout.reconfigure(encoding="utf-8")

EXA_API_KEY      = os.getenv("EXA_API_KEY", "")
OPENROUTER_KEY   = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
MODEL_ID         = "openai/gpt-oss-120b"

THIS_DIR         = Path(__file__).parent
CANADA_CSV       = Path(__file__).parent.parent / "data" / "canada_usable_296.csv"
MATRIX_PATH      = THIS_DIR / "matrix.json"
EXTRACT_PROMPT_PATH = THIS_DIR / "extraction_prompt_final.txt"
IB_PROMPT_PATH   = THIS_DIR / "icebreaker_prompt_final.txt"
COPY_DIR         = THIS_DIR / "copy"
EXTRACT_DIR      = THIS_DIR / "extractions"
CAMPAIGNS_DIR    = THIS_DIR / "campaigns"

MATRIX            = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
EXTRACTION_PROMPT = EXTRACT_PROMPT_PATH.read_text(encoding="utf-8")
IB_PROMPT         = IB_PROMPT_PATH.read_text(encoding="utf-8")


# ── exa fetch ─────────────────────────────────────────────────────────────────

async def exa_fetch_one(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    url: str,
) -> tuple[str, str]:
    """Returns (url, text). text is empty string on failure."""
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "http://" + clean_url

    payload = {
        "ids": [clean_url],
        "text": {"maxCharacters": 4000, "verbosity": "standard"},
    }
    async with sem:
        try:
            async with session.post(
                "https://api.exa.ai/contents",
                json=payload,
                headers={"x-api-key": EXA_API_KEY, "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    return url, ""
                data = await resp.json()
                results = data.get("results", [])
                if not results:
                    return url, ""
                text = (results[0].get("text") or "").strip()
                return url, text
        except Exception:
            return url, ""


async def exa_fetch_batch(
    url_row_pairs: list[tuple[str, dict]],
    concurrency: int = 50,
) -> dict[str, str]:
    """Returns {url: text}."""
    sem = asyncio.Semaphore(concurrency)
    url_to_text: dict[str, str] = {}
    done = 0
    t0 = time.time()

    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(exa_fetch_one(session, sem, url))
            for url, _ in url_row_pairs
        ]
        for coro in asyncio.as_completed(tasks):
            url, text = await coro
            url_to_text[url] = text
            done += 1
            speed = done / max(time.time() - t0, 0.1)
            ok = sum(1 for v in url_to_text.values() if v)
            print(f"  exa {done}/{len(url_row_pairs)} | {speed:.1f}/s | ok={ok}", end="\r")

    print()
    return url_to_text


# ── extraction ─────────────────────────────────────────────────────────────────

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


def build_extraction_prompt(row: dict, website_text: str) -> str:
    p = EXTRACTION_PROMPT
    p = p.replace("{{Website Summary}}",        website_text[:3000] if website_text else "")
    p = p.replace("{{Company Short Description}}", row.get("Company Short Description", "") or "")
    p = p.replace("{{Company Name}}",           row.get("Company Name", "") or "")
    p = p.replace("{{Company Website}}",        row.get("Company Website", "") or "")
    p = p.replace("{{Keywords}}",               row.get("Keywords", "") or "")
    return p


async def llm_call(client: httpx.AsyncClient, sem: asyncio.Semaphore, prompt: str, temperature: float = 0.1) -> tuple[str, float]:
    t0 = time.monotonic()
    payload = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "provider": {"sort": "throughput"},
    }
    try:
        async with sem:
            resp = await client.post(OPENROUTER_URL, json=payload, timeout=90.0)
            elapsed = time.monotonic() - t0
            if resp.status_code != 200:
                return f"ERROR: HTTP {resp.status_code}", elapsed
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            return (content or "").strip(), elapsed
    except Exception as e:
        return f"ERROR: {e}", time.monotonic() - t0


async def run_extraction(
    rows: list[dict],
    url_to_text: dict[str, str],
    concurrency: int,
) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
    results = []
    done = 0
    t0 = time.time()

    async def extract_one(i: int, row: dict) -> dict:
        website = (row.get("Company Website") or "").strip()
        text = url_to_text.get(website, "")
        if not text and not website.startswith("http"):
            text = url_to_text.get("http://" + website, "")
        prompt = build_extraction_prompt(row, text)
        raw, elapsed = await llm_call(client, sem, prompt, temperature=0.1)
        extracted = parse_json(raw)
        return {
            "_idx":             i,
            "_first_name":      row.get("First Name", ""),
            "_last_name":       row.get("Last Name", ""),
            "_company_name":    row.get("Company Name", ""),
            "_company_website": row.get("Company Website", ""),
            "_country":         row.get("Country", "Canada"),
            "_email":           row.get("Email", ""),
            "_linkedin":        row.get("LinkedIn", ""),
            "_company_linkedin":row.get("Company Linkedin", ""),
            "_headline":        row.get("Headline", ""),
            "_title":           row.get("Title", ""),
            "_state":           row.get("State", ""),
            "_exa_chars":       len(text),
            "_t_extract_s":     round(elapsed, 2),
            **extracted,
        }

    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [asyncio.create_task(extract_one(i, row)) for i, row in enumerate(rows)]
        for coro in asyncio.as_completed(tasks):
            r = await coro
            results.append(r)
            done += 1
            speed = done / max(time.time() - t0, 0.1)
            print(f"  extract {done}/{len(rows)} | {speed:.1f}/s", end="\r")

    print()
    results.sort(key=lambda x: x["_idx"])
    return results


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


# ── postprocess ────────────────────────────────────────────────────────────────

_CONCAT_FIXES = [
    (re.compile(r"saying they", re.I), "saying they"),
    (re.compile(r"sayingthey"),       "saying they"),
    (re.compile(r"i'dreach"),         "i'd reach"),
    (re.compile(r"reach ?out(?=[^a-z])"), "reach out"),
    (re.compile(r"\bof founders\b"),  "of founders"),
    (re.compile(r"\boffounders\b"),   "of founders"),
    (re.compile(r"background ?checks"), "background checks"),
    (re.compile(r"backgroundcheck"),  "background checks"),
    (re.compile(r"dealing witha\b"),  "dealing with a"),
    (re.compile(r"andthey\b"),        "and they"),
    (re.compile(r"inthey\b"),         "in they"),
    (re.compile(r"\bVP sales\b"),     "VP Sales"),
]

_ACRONYM_RE = [
    (re.compile(r'\bhr\b'),   "HR"),
    (re.compile(r'\bvp\b'),   "VP"),
    (re.compile(r'\bceo\b'),  "CEO"),
    (re.compile(r'\bcoo\b'),  "COO"),
    (re.compile(r'\bcfo\b'),  "CFO"),
    (re.compile(r'\bcto\b'),  "CTO"),
    (re.compile(r'\bgm\b'),   "GM"),
    (re.compile(r'\bit\b(?= (services|manager|lead|team|director|staffing|firms|company|companies|consulting))'), "IT"),
    (re.compile(r'\bai\b(?= (companies|startups|firm|sector|industry|cto|space|tools|models))'), "AI"),
    (re.compile(r'\bsaas\b'), "SaaS"),
    (re.compile(r'\bml\b'),   "ML"),
]


def postprocess(line: str, uppercase_acronyms: bool = True) -> str:
    for pattern, replacement in _CONCAT_FIXES:
        line = pattern.sub(replacement, line)
    if uppercase_acronyms:
        for pattern, replacement in _ACRONYM_RE:
            line = pattern.sub(replacement, line)
    line = re.sub(r'  +', ' ', line).strip()
    return line


# ── icebreaker ─────────────────────────────────────────────────────────────────

def build_ib_prompt(row: dict, matrix_entry: dict, pain: str) -> str:
    p = IB_PROMPT
    p = p.replace("{{dreamICP_base}}",    matrix_entry.get("dreamICP", ""))
    p = p.replace("{{pain_base}}",        pain)
    p = p.replace("{{company_name}}",     row.get("_company_name", ""))
    p = p.replace("{{country}}",          row.get("_country", "Canada"))
    p = p.replace("{{client_profile}}",   row.get("client_profile", "unknown"))
    p = p.replace("{{detected_signals}}", (row.get("detected_signals", "") or "")[:300])
    return p


TEMPLATE_A = None
TEMPLATE_B = None


def load_templates():
    global TEMPLATE_A, TEMPLATE_B
    def load(path):
        raw = path.read_text(encoding="utf-8")
        lines = raw.split("\n")
        body_lines = []
        in_body = False
        for line in lines:
            if line.strip() == "---":
                in_body = True
                continue
            if in_body:
                body_lines.append(line)
        return "\n".join(body_lines).strip()

    TEMPLATE_A = load(COPY_DIR / "variant_A.txt")
    TEMPLATE_B = load(COPY_DIR / "variant_B.txt")


def assemble_email(template: str, personalisation: str, first_name: str, lowercase: bool) -> str:
    display = first_name if first_name else "there"
    if lowercase:
        display = display.lower()
        personalisation = personalisation.lower()
    email = template
    email = email.replace("{{first_name}}", display)
    email = email.replace("{{custom_personalisation}}", personalisation)
    return email


async def run_icebreakers(
    extractions: list[dict],
    concurrency: int,
) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
    results = []
    done = 0
    t0 = time.time()

    async def gen_one(row: dict) -> dict:
        svc   = row.get("primary_service") or "unknown"
        sub   = row.get("sub_industry") or "null"
        entry = matrix_lookup(svc, sub)
        pain  = entry.get("pain", "")

        prompt = build_ib_prompt(row, entry, pain)
        raw, elapsed = await llm_call(client, sem, prompt, temperature=0.3)

        if not raw.startswith("ERROR"):
            icebreaker_a = postprocess(raw, uppercase_acronyms=True)
            icebreaker_b = postprocess(raw, uppercase_acronyms=False).lower()
        else:
            icebreaker_a = raw
            icebreaker_b = raw

        first_name = row.get("_first_name", "") or ""
        email_a = assemble_email(TEMPLATE_A, icebreaker_a, first_name, lowercase=False)
        email_b = assemble_email(TEMPLATE_B, icebreaker_b, first_name, lowercase=True)

        return {
            "_idx":             row.get("_idx"),
            "first_name":       first_name,
            "last_name":        row.get("_last_name", ""),
            "email":            row.get("_email", ""),
            "linkedin_url":     row.get("_linkedin", ""),
            "company_linkedin_url": row.get("_company_linkedin", ""),
            "company_name":     row.get("_company_name", ""),
            "clean_company":    row.get("_clean_company") or row.get("_company_name", ""),
            "country":          row.get("_country", "Canada"),
            "state":            row.get("_state", ""),
            "headline":         row.get("_headline", ""),
            "title":            row.get("_title", ""),
            "primary_service":  svc,
            "sub_industry":     sub,
            "client_profile":   row.get("client_profile", ""),
            "matrix_key":       f"{svc}__{sub}",
            "matrix_pain":      pain,
            "icebreaker":       icebreaker_a,
            "email_a_dealflow": email_a,
            "email_b_lowercase": email_b,
            "_exa_chars":       row.get("_exa_chars", 0),
            "_t_s":             round(elapsed, 2),
        }

    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [asyncio.create_task(gen_one(row)) for row in extractions]
        for coro in asyncio.as_completed(tasks):
            r = await coro
            results.append(r)
            done += 1
            speed = done / max(time.time() - t0, 0.1)
            print(f"  icebreakers {done}/{len(extractions)} | {speed:.1f}/s", end="\r")

    print()
    results.sort(key=lambda x: (x["_idx"] or 0))
    return results


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample",      type=int,  default=None)
    parser.add_argument("--concurrency", type=int,  default=40)
    parser.add_argument("--skip-exa",   action="store_true",
                        help="Skip Exa fetch — use Company Short Description only")
    parser.add_argument("--exa-only",   action="store_true",
                        help="Only fetch Exa + run extraction, save JSONL, no icebreakers")
    parser.add_argument("--from-jsonl", type=str, default=None,
                        help="Skip Exa+extraction, load existing JSONL, run icebreakers only")
    args = parser.parse_args()

    if not OPENROUTER_KEY:
        print("ERROR: OPENROUTER_API_KEY not set")
        sys.exit(1)
    if not args.skip_exa and not args.from_jsonl and not EXA_API_KEY:
        print("ERROR: EXA_API_KEY not set")
        sys.exit(1)

    load_templates()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    EXTRACT_DIR.mkdir(exist_ok=True)
    CAMPAIGNS_DIR.mkdir(exist_ok=True)

    # ── load rows ────────────────────────────────────────────────────────────────

    if args.from_jsonl:
        jsonl_path = Path(args.from_jsonl)
        print(f"Loading extractions: {jsonl_path.name}")
        extractions = [json.loads(l) for l in open(jsonl_path, encoding="utf-8") if l.strip()]
        extractions.sort(key=lambda x: x.get("_idx", 0))
        print(f"Loaded {len(extractions)} records")
    else:
        with open(CANADA_CSV, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if args.sample:
            rows = rows[:args.sample]
        print(f"Canada leads: {len(rows)}")

        # ── step 1: exa fetch ────────────────────────────────────────────────────
        url_to_text: dict[str, str] = {}
        if not args.skip_exa:
            url_row_pairs = [(r.get("Company Website", ""), r) for r in rows if r.get("Company Website", "").strip()]
            missing = len(rows) - len(url_row_pairs)
            if missing:
                print(f"  {missing} rows have no Company Website — will use Short Description only")
            print(f"\nStep 1: Exa fetch ({len(url_row_pairs)} URLs, concurrency={args.concurrency})")
            t0 = time.time()
            url_to_text = asyncio.run(exa_fetch_batch(url_row_pairs, concurrency=args.concurrency))
            elapsed = time.time() - t0
            ok = sum(1 for v in url_to_text.values() if v)
            avg_chars = sum(len(v) for v in url_to_text.values() if v) / max(ok, 1)
            print(f"Exa done: {ok}/{len(url_row_pairs)} ok | avg {avg_chars:.0f} chars | {elapsed:.1f}s")
        else:
            print("Skipping Exa fetch (--skip-exa)")

        # ── step 2: extraction ───────────────────────────────────────────────────
        print(f"\nStep 2: Extraction ({len(rows)} rows, concurrency={args.concurrency})")
        t0 = time.time()
        extractions = asyncio.run(run_extraction(rows, url_to_text, concurrency=args.concurrency))
        elapsed = time.time() - t0
        errors = sum(1 for r in extractions if r.get("error"))
        print(f"Extraction done: {elapsed:.1f}s | errors={errors}")

        jsonl_path = EXTRACT_DIR / f"canada_extraction_{ts}.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for r in extractions:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"Saved: {jsonl_path.name}")

        if args.exa_only:
            print("Done (--exa-only)")
            return

    # ── step 3: icebreaker generation ────────────────────────────────────────────
    print(f"\nStep 3: Icebreaker generation ({len(extractions)} rows, concurrency={args.concurrency})")
    t0 = time.time()
    results = asyncio.run(run_icebreakers(extractions, concurrency=args.concurrency))
    elapsed = time.time() - t0
    errors = sum(1 for r in results if str(r.get("icebreaker", "")).startswith("ERROR"))
    print(f"Icebreakers done: {elapsed:.1f}s | errors={errors}")

    # ── step 4: save campaign CSV ─────────────────────────────────────────────────
    out_path = CAMPAIGNS_DIR / f"canada_ab_test_{datetime.now().strftime('%Y%m%d')}.csv"
    fields = [
        "first_name", "last_name", "email", "linkedin_url", "company_linkedin_url",
        "company_name", "clean_company", "country", "state", "headline", "title",
        "primary_service", "sub_industry", "client_profile",
        "matrix_key", "matrix_pain", "icebreaker",
        "email_a_dealflow", "email_b_lowercase",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    print(f"\nSaved: {out_path.name}")
    print(f"Total: {len(results)} | Errors: {errors}")

    print("\n--- SAMPLE (first 3) ---")
    for r in results[:3]:
        print(f"\n{'='*60}")
        print(f"[{r['_idx']}] {r['company_name']} | {r['country']} | {r['matrix_key']}")
        print(f"{'='*60}")
        print(r["email_a_dealflow"])


if __name__ == "__main__":
    main()

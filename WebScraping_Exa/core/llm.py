"""
core/llm.py — OpenRouter LLM extraction with structured JSON output
Prompts loaded from prompts/*.txt dynamically.
system_context.txt prepended to every call.

CLI:
    py core/llm.py --input file.csv --text-col "Website Summary" --limit 5 --prompt company_full
"""

import asyncio
import argparse
import json
import re
import sys
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_TEMPERATURE = 0.1
CONFIDENCE_THRESHOLD = 6


@dataclass
class LLMResult:
    url: str
    data: dict = field(default_factory=dict)
    confidence: int = 0
    ok: bool = False
    error: str | None = None
    input_chars: int = 0
    elapsed_ms: int = 0


# ── Prompt manager ─────────────────────────────────────────────────────────────

def list_prompts() -> list[str]:
    return sorted([
        p.stem for p in PROMPTS_DIR.glob("*.txt")
        if p.stem != "system_context"
    ])


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def load_system_context() -> str:
    from core.prompts_store import get_system_context
    return get_system_context()


def build_messages(prompt_name: str, text: str) -> list[dict]:
    system = load_system_context()
    user_template = load_prompt(prompt_name)
    user = user_template.format(text=text)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ── JSON parser ────────────────────────────────────────────────────────────────

def parse_json_response(raw: str) -> dict:
    # убрать ```json ... ``` обёртку
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    # попробовать напрямую
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # найти первый {...} блок
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass

    # полный fallback
    return {"raw": raw, "confidence": 0}


# ── Core async function ────────────────────────────────────────────────────────

async def extract(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    url: str,
    text: str,
    prompt_name: str = "company_full",
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
) -> LLMResult:
    t0 = time.monotonic()

    if not text or not text.strip():
        return LLMResult(url=url, ok=False, error="empty_text",
                         confidence=0, input_chars=0)

    try:
        messages = build_messages(prompt_name, text)
    except FileNotFoundError as e:
        return LLMResult(url=url, ok=False, error=str(e))

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "provider": {"sort": "throughput"},  # КРИТИЧНО — иначе 7x медленнее
    }

    async with sem:
        try:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                timeout=90.0,
            )
            elapsed = int((time.monotonic() - t0) * 1000)

            if resp.status_code != 200:
                return LLMResult(url=url, ok=False,
                                 error=f"HTTP {resp.status_code}: {resp.text[:120]}",
                                 elapsed_ms=elapsed)

            data = resp.json()
            raw_content = data["choices"][0]["message"]["content"]
            if not raw_content:
                return LLMResult(url=url, ok=False, error="empty_response",
                                 elapsed_ms=elapsed)
            parsed = parse_json_response(raw_content)
            confidence = int(parsed.get("confidence", 0))

            return LLMResult(
                url=url,
                data=parsed,
                confidence=confidence,
                ok=True,
                input_chars=len(text),
                elapsed_ms=elapsed,
            )

        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            return LLMResult(url=url, ok=False, error=str(e)[:120], elapsed_ms=elapsed)


async def extract_batch(
    items: list[dict],          # [{"url": str, "text": str}, ...]
    prompt_name: str = "company_full",
    concurrency: int = 50,
    model: str = DEFAULT_MODEL,
    api_key: str = "",
    progress: bool = False,
) -> list[LLMResult]:
    key = api_key or OPENROUTER_API_KEY
    if not key:
        raise ValueError("OPENROUTER_API_KEY not set")

    sem = asyncio.Semaphore(concurrency)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    results: list[LLMResult] = []
    t0 = time.time()

    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [
            asyncio.create_task(extract(
                client, sem,
                item["url"], item["text"],
                prompt_name=prompt_name,
                model=model,
            ))
            for item in items
        ]

        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)

            if progress:
                n = len(results)
                elapsed = time.time() - t0
                speed = n / elapsed if elapsed > 0 else 0
                eta = int((len(items) - n) / speed) if speed > 0 else 0
                ok = sum(1 for r in results if r.ok)
                low_conf = sum(1 for r in results if r.ok and r.confidence < CONFIDENCE_THRESHOLD)
                print(f"  {n}/{len(items)} | {speed:.1f}/sec | ETA {eta}s | "
                      f"ok={ok} | low_conf={low_conf}", end="\r")

    if progress:
        print()

    # восстанавливаем порядок
    url_order = {item["url"]: i for i, item in enumerate(items)}
    results.sort(key=lambda r: url_order.get(r.url, 9999))
    return results


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--input",    required=True)
    parser.add_argument("--url-col",  default=None, help="URL column name")
    parser.add_argument("--text-col", default=None, help="Existing text column (skip Exa if present)")
    parser.add_argument("--limit",    type=int, default=5)
    parser.add_argument("--prompt",   default="company_full")
    parser.add_argument("--concurrency", type=int, default=50)
    args = parser.parse_args()

    if not OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set in .env")
        sys.exit(1)

    print(f"Available prompts: {list_prompts()}")

    df = pd.read_csv(args.input)

    # авто-детект URL колонки
    url_col = args.url_col
    if not url_col:
        for col in df.columns:
            if any(k in col.lower() for k in ["website", "url", "site", "domain"]):
                url_col = col
                break

    # авто-детект text колонки
    text_col = args.text_col

    rows = df.head(args.limit) if args.limit else df

    items = []
    for _, row in rows.iterrows():
        url = str(row.get(url_col, "")).strip() if url_col else ""
        text = str(row.get(text_col, "")).strip() if text_col else ""
        if text and text not in ("nan", "None", "none"):
            items.append({"url": url or text[:50], "text": text})

    if not items:
        print(f"ERROR: no text found in column '{text_col}'")
        sys.exit(1)

    print(f"\nRunning LLM on {len(items)} items | prompt={args.prompt} | concurrency={args.concurrency}\n")

    t0 = time.time()
    results = asyncio.run(extract_batch(
        items,
        prompt_name=args.prompt,
        concurrency=args.concurrency,
        progress=True,
    ))
    elapsed = time.time() - t0

    ok_results   = [r for r in results if r.ok]
    err_results  = [r for r in results if not r.ok]
    low_conf     = [r for r in ok_results if r.confidence < CONFIDENCE_THRESHOLD]
    high_conf    = [r for r in ok_results if r.confidence >= CONFIDENCE_THRESHOLD]

    print("=" * 65)
    print(f"Done: {len(items)} items in {elapsed:.1f}s ({len(items)/elapsed:.1f}/sec)")
    print(f"OK:        {len(ok_results)} ({len(ok_results)/len(results)*100:.0f}%)")
    print(f"High conf (>={CONFIDENCE_THRESHOLD}): {len(high_conf)} → ready")
    print(f"Low conf  (<{CONFIDENCE_THRESHOLD}):  {len(low_conf)} → need subpages")
    print(f"Errors:    {len(err_results)}")
    print()

    for r in ok_results[:3]:
        print(f"URL: {r.url[:60]}")
        print(f"Confidence: {r.confidence}/10")
        for k, v in r.data.items():
            if k in ("summary", "raw"):
                print(f"  {k}: {str(v)[:150]}...")
            elif k != "confidence":
                print(f"  {k}: {v}")
        print()

    if err_results:
        print("Errors:")
        for r in err_results[:3]:
            print(f"  {r.url[:50]}: {r.error}")


if __name__ == "__main__":
    main()

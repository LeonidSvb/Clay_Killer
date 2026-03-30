"""
core/exa.py — Exa API wrapper
Returns raw text only (no Exa summary — LLM does that).
Supports subpages for Pass 3 (low confidence retry).

CLI:
    py core/exa.py --input file.csv --col "Company Website" --limit 10
    py core/exa.py --input file.csv --col "Company Website" --limit 5 --subpages 3
"""

import asyncio
import argparse
import time
import os
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp
import pandas as pd
from dotenv import load_dotenv

warnings.filterwarnings("ignore")

load_dotenv(Path(__file__).parent.parent / ".env")
EXA_API_KEY = os.getenv("EXA_API_KEY", "")

DEFAULT_SUBPAGE_TARGETS = [
    "about", "services", "solutions", "clients",
    "industries", "who-we-serve", "what-we-do", "products"
]


@dataclass
class PageContent:
    url: str
    text: str
    char_count: int
    source: str = "exa"


@dataclass
class ExaResult:
    url: str
    pages: list[PageContent] = field(default_factory=list)
    total_text: str = ""
    total_chars: int = 0
    ok: bool = False
    error: str | None = None


def build_total_text(pages: list[PageContent]) -> str:
    parts = []
    for p in pages:
        if p.text.strip():
            parts.append(f"[PAGE: {p.url}]\n{p.text.strip()}")
    return "\n\n".join(parts)


async def fetch_url(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    url: str,
    subpages: int = 0,
    subpage_targets: list[str] | None = None,
    max_age_hours: int = 24,
    text_max_chars: int = 5000,
    timeout: int = 60,
    api_key: str = "",
) -> ExaResult:
    key = api_key or EXA_API_KEY
    targets = subpage_targets or DEFAULT_SUBPAGE_TARGETS

    # нормализуем URL
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "http://" + clean_url

    payload: dict = {
        "ids": [clean_url],
        "maxAgeHours": max_age_hours,
        "text": {
            "maxCharacters": text_max_chars,
            "verbosity": "standard",
        },
    }
    if subpages > 0:
        payload["subpages"] = subpages
        payload["subpage_target"] = targets

    async with sem:
        try:
            async with session.post(
                "https://api.exa.ai/contents",
                json=payload,
                headers={
                    "x-api-key": key,
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    return ExaResult(url=url, ok=False, error=f"HTTP {resp.status}: {err[:120]}")

                data = await resp.json()
                results = data.get("results", [])

                if not results:
                    return ExaResult(url=url, ok=False, error="empty_results")

                r = results[0]
                pages: list[PageContent] = []

                # main page
                main_text = (r.get("text") or "").strip()
                if main_text:
                    pages.append(PageContent(
                        url=r.get("url", clean_url),
                        text=main_text,
                        char_count=len(main_text),
                    ))

                # subpages
                for sub in r.get("subpages", []):
                    sub_text = (sub.get("text") or "").strip()
                    if sub_text:
                        pages.append(PageContent(
                            url=sub.get("url", ""),
                            text=sub_text,
                            char_count=len(sub_text),
                        ))

                if not pages:
                    return ExaResult(url=url, ok=False, error="empty_text")

                total_text = build_total_text(pages)
                return ExaResult(
                    url=url,
                    pages=pages,
                    total_text=total_text,
                    total_chars=len(total_text),
                    ok=True,
                )

        except asyncio.TimeoutError:
            return ExaResult(url=url, ok=False, error="timeout")
        except Exception as e:
            return ExaResult(url=url, ok=False, error=f"error: {str(e)[:100]}")


async def fetch_batch(
    urls: list[str],
    concurrency: int = 50,
    subpages: int = 0,
    subpage_targets: list[str] | None = None,
    max_age_hours: int = 24,
    text_max_chars: int = 5000,
    api_key: str = "",
    progress: bool = False,
) -> list[ExaResult]:
    sem = asyncio.Semaphore(concurrency)
    results: list[ExaResult] = []
    t0 = time.time()

    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(fetch_url(
                session, sem, url,
                subpages=subpages,
                subpage_targets=subpage_targets,
                max_age_hours=max_age_hours,
                text_max_chars=text_max_chars,
                api_key=api_key,
            ))
            for url in urls
        ]

        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)

            if progress:
                n = len(results)
                elapsed = time.time() - t0
                speed = n / elapsed if elapsed > 0 else 0
                eta = int((len(urls) - n) / speed) if speed > 0 else 0
                ok = sum(1 for r in results if r.ok)
                print(f"  {n}/{len(urls)} | {speed:.1f}/sec | ETA {eta}s | ok={ok}", end="\r")

    if progress:
        print()

    # восстанавливаем оригинальный порядок
    url_order = {url: i for i, url in enumerate(urls)}
    results.sort(key=lambda r: url_order.get(r.url, 9999))
    return results


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--col", default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--subpages", type=int, default=0)
    parser.add_argument("--max-age-hours", type=int, default=24)
    parser.add_argument("--concurrency", type=int, default=50)
    args = parser.parse_args()

    if not EXA_API_KEY:
        print("ERROR: EXA_API_KEY not set in .env")
        sys.exit(1)

    df = pd.read_csv(args.input)

    # авто-детект колонки
    url_col = args.col
    if not url_col:
        for col in df.columns:
            if any(k in col.lower() for k in ["website", "url", "site", "domain"]):
                url_col = col
                break

    urls = df[url_col].dropna().astype(str).str.strip().tolist()
    urls = [u for u in urls if u and u != "nan"]
    if args.limit:
        urls = urls[:args.limit]

    print(f"Fetching {len(urls)} URLs | subpages={args.subpages} | "
          f"maxAgeHours={args.max_age_hours} | concurrency={args.concurrency}\n")

    t0 = time.time()
    results = asyncio.run(fetch_batch(
        urls,
        concurrency=args.concurrency,
        subpages=args.subpages,
        max_age_hours=args.max_age_hours,
        progress=True,
    ))
    elapsed = time.time() - t0

    ok_results  = [r for r in results if r.ok]
    err_results = [r for r in results if not r.ok]

    print("=" * 60)
    print(f"Done: {len(urls)} URLs in {elapsed:.1f}s ({len(urls)/elapsed:.1f} URL/sec)")
    print(f"OK:   {len(ok_results)} ({len(ok_results)/len(results)*100:.0f}%)")
    print(f"Fail: {len(err_results)} ({len(err_results)/len(results)*100:.0f}%)")
    print()

    if ok_results:
        avg_chars = sum(r.total_chars for r in ok_results) / len(ok_results)
        avg_pages = sum(len(r.pages) for r in ok_results) / len(ok_results)
        print(f"Avg text:  {avg_chars:.0f} chars per lead")
        print(f"Avg pages: {avg_pages:.1f} per lead")
        print()

    print("Sample results:")
    for r in ok_results[:5]:
        pages_info = f"{len(r.pages)} page(s)"
        print(f"  OK  | {r.url[:55]:55s} | {r.total_chars:5d} chars | {pages_info}")
        print(f"       preview: {r.total_text[:120].replace(chr(10), ' ')}...")
        print()

    if err_results:
        print("Errors:")
        err_types: dict[str, int] = {}
        for r in err_results:
            key = (r.error or "unknown").split(":")[0]
            err_types[key] = err_types.get(key, 0) + 1
        for k, v in sorted(err_types.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")

    print()
    exa_cost = len(ok_results) * 0.001
    if args.subpages > 0:
        exa_cost += sum(max(0, len(r.pages) - 1) for r in ok_results) * 0.001
    print(f"Estimated cost: ${exa_cost:.3f}")


if __name__ == "__main__":
    main()

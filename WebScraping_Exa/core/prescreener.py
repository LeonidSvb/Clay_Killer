"""
core/prescreener.py — Pass 0: async URL classifier
Classifies URLs as: html_light / js_heavy / blocked / dead

CLI:
    py core/prescreener.py --input file.csv --col company_website --limit 100
"""

import asyncio
import argparse
import time
import re
import sys
from dataclasses import dataclass
from typing import Literal
from pathlib import Path

import aiohttp
import pandas as pd
from bs4 import BeautifulSoup

SiteClass = Literal["html_light", "js_heavy", "blocked", "dead"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

JS_SIGNATURES = [
    '<div id="root"></div>',
    '<div id="root">',
    '<div id="app"></div>',
    '<div id="app">',
    "window.__NEXT_DATA__",
    "window.__NUXT__",
    'ng-version="',
    "__REACT_APP",
    "data-reactroot",
    "__vue__",
]

BLOCKED_SIGNATURES = [
    "just a moment",
    "enable javascript and cookies",
    "checking your browser",
    "ddos-guard",
    "please wait while we verify",
]

MIN_TEXT_LENGTH = 300


@dataclass
class ScreenResult:
    url: str
    site_class: SiteClass
    text_length: int
    reason: str
    elapsed_ms: int


def extract_visible_text(html: str) -> str:
    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "form", "iframe"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
    except Exception:
        return ""


async def screen_url(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    url: str,
    timeout: int = 8,
    max_bytes: int = 10_000,
) -> ScreenResult:
    t0 = time.monotonic()

    # нормализуем URL
    raw_url = url.strip()
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "http://" + raw_url

    async with sem:
        try:
            async with session.get(
                raw_url,
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=True,
                ssl=False,
            ) as resp:
                elapsed = int((time.monotonic() - t0) * 1000)
                status = resp.status

                # BLOCKED by status code
                if status in (403, 503, 429, 503):
                    return ScreenResult(url=url, site_class="blocked",
                                        text_length=0, reason=f"HTTP {status}",
                                        elapsed_ms=elapsed)

                # читаем только первые max_bytes
                raw = b""
                async for chunk in resp.content.iter_chunked(1024):
                    raw += chunk
                    if len(raw) >= max_bytes:
                        break

                html = raw.decode("utf-8", errors="ignore")
                html_lower = html.lower()

                # BLOCKED by content (Cloudflare challenge)
                for sig in BLOCKED_SIGNATURES:
                    if sig in html_lower:
                        return ScreenResult(url=url, site_class="blocked",
                                            text_length=0, reason=f"challenge: {sig[:30]}",
                                            elapsed_ms=elapsed)

                # Cloudflare by header
                if "cf-ray" in {k.lower() for k in resp.headers.keys()}:
                    # cf-ray присутствует — но может быть нормальный сайт за CF
                    # только если тело пустое или tiny считаем blocked
                    if len(html) < 500:
                        return ScreenResult(url=url, site_class="blocked",
                                            text_length=0, reason="cloudflare+empty",
                                            elapsed_ms=elapsed)

                # JS_HEAVY detection
                for sig in JS_SIGNATURES:
                    if sig.lower() in html_lower:
                        return ScreenResult(url=url, site_class="js_heavy",
                                            text_length=0, reason=f"js_sig: {sig[:40]}",
                                            elapsed_ms=elapsed)

                # извлекаем видимый текст
                text = extract_visible_text(html)
                text_len = len(text)

                # если текст слишком маленький — JS рендерит контент
                # убрали ограничение на len(html) — большой HTML с малым текстом тоже JS
                if text_len < MIN_TEXT_LENGTH:
                    return ScreenResult(url=url, site_class="js_heavy",
                                        text_length=text_len, reason=f"sparse_text={text_len}chars",
                                        elapsed_ms=elapsed)

                return ScreenResult(url=url, site_class="html_light",
                                    text_length=text_len, reason=f"text={text_len}chars",
                                    elapsed_ms=elapsed)

        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - t0) * 1000)
            return ScreenResult(url=url, site_class="dead",
                                text_length=0, reason="timeout",
                                elapsed_ms=elapsed)
        except aiohttp.ClientConnectorError as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            return ScreenResult(url=url, site_class="dead",
                                text_length=0, reason=f"dns_fail: {str(e)[:60]}",
                                elapsed_ms=elapsed)
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            return ScreenResult(url=url, site_class="dead",
                                text_length=0, reason=f"error: {str(e)[:60]}",
                                elapsed_ms=elapsed)


async def screen_batch(
    urls: list[str],
    concurrency: int = 100,
    timeout: int = 8,
) -> list[ScreenResult]:
    sem = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit=concurrency, ssl=False)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            asyncio.create_task(screen_url(session, sem, url, timeout))
            for url in urls
        ]
        results = []
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)

    # сортируем по исходному порядку
    url_order = {url: i for i, url in enumerate(urls)}
    results.sort(key=lambda r: url_order.get(r.url, 9999))
    return results


def detect_url_col(df: pd.DataFrame) -> str | None:
    keywords = ["website", "url", "site", "domain", "web", "link"]
    for kw in keywords:
        for col in df.columns:
            if kw in col.lower():
                return col
    # по содержимому
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(20)
        hits = sample.str.contains(r'\.[a-z]{2,}', regex=True, na=False).sum()
        if hits >= len(sample) * 0.5:
            return col
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--col", default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=100)
    args = parser.parse_args()

    df = pd.read_csv(args.input)

    url_col = args.col or detect_url_col(df)
    if not url_col:
        print("ERROR: URL column not found. Use --col")
        sys.exit(1)

    print(f"File: {args.input}")
    print(f"Rows: {len(df)} | URL column: '{url_col}'")

    urls = df[url_col].dropna().astype(str).str.strip().tolist()
    urls = [u for u in urls if u and u != "nan"]

    if args.limit:
        urls = urls[:args.limit]

    print(f"Screening {len(urls)} URLs | concurrency={args.concurrency}\n")

    t0 = time.time()
    results = asyncio.run(screen_batch(urls, concurrency=args.concurrency))
    elapsed = time.time() - t0

    # статистика
    classes = {}
    for r in results:
        classes[r.site_class] = classes.get(r.site_class, 0) + 1

    total = len(results)
    print("=" * 55)
    print(f"Results: {total} URLs in {elapsed:.1f}s ({total/elapsed:.1f} URL/sec)")
    print("=" * 55)
    for cls in ["html_light", "js_heavy", "blocked", "dead"]:
        n = classes.get(cls, 0)
        pct = n / total * 100 if total else 0
        bar = "#" * int(pct / 2)
        print(f"  {cls:12s}: {n:4d} ({pct:5.1f}%)  {bar}")

    print()
    for cls in ["html_light", "js_heavy", "blocked", "dead"]:
        examples = [r for r in results if r.site_class == cls][:3]
        if examples:
            print(f"[{cls}] examples:")
            for r in examples:
                print(f"  {r.url[:60]:60s}  reason={r.reason[:50]}")
            print()

    # avg text length for html_light
    html_results = [r for r in results if r.site_class == "html_light"]
    if html_results:
        avg_text = sum(r.text_length for r in html_results) / len(html_results)
        print(f"html_light avg text length: {avg_text:.0f} chars")
        print()

    # savings estimate
    exa_needed = classes.get("js_heavy", 0) + classes.get("blocked", 0)
    free_scraped = classes.get("html_light", 0)
    print(f"Exa pages needed (hybrid mode): {exa_needed} (~${exa_needed * 0.001:.2f})")
    print(f"Free via custom scraper:        {free_scraped} (saved ~${free_scraped * 0.001:.2f})")


if __name__ == "__main__":
    main()

"""
icebreakers_round_robin/detect_js.py

Checks first 30 lines of HTML to classify site as js_heavy or static.
Fast: streams only first 4KB, no full page download.

Usage:
    py icebreakers_round_robin/detect_js.py --url https://example.com
    py icebreakers_round_robin/detect_js.py --csv data/canada_usable_296.csv --col "Company Website" --sample 20

Importable:
    from icebreakers_round_robin.detect_js import classify_batch
    results = asyncio.run(classify_batch(urls))
"""

import asyncio
import argparse
import csv
import re
import sys
import time
from pathlib import Path

import aiohttp

sys.stdout.reconfigure(encoding="utf-8")

READ_BYTES  = 4096   # first 4KB is enough
HEAD_LINES  = 30     # check only first N lines of HTML
TIMEOUT_S   = 10
CONCURRENCY = 50


# ── JS-heavy signals ──────────────────────────────────────────────────────────
# Each tuple: (pattern, weight, label)
JS_SIGNALS = [
    # SPA roots
    (re.compile(r'id=["\']root["\']',        re.I), 3, "react/vue root div"),
    (re.compile(r'id=["\']app["\']',          re.I), 2, "vue/generic spa root"),
    (re.compile(r'id=["\']__nuxt["\']',       re.I), 3, "nuxt.js"),
    (re.compile(r'id=["\']gatsby-',           re.I), 3, "gatsby"),

    # Framework artifacts in script src
    (re.compile(r'/_next/static/',            re.I), 4, "next.js"),
    (re.compile(r'/static/js/main\.',         re.I), 3, "create-react-app"),
    (re.compile(r'angular',                   re.I), 2, "angular"),
    (re.compile(r'ng-version=',               re.I), 4, "angular"),
    (re.compile(r'svelte',                    re.I), 2, "svelte"),
    (re.compile(r'__NEXT_DATA__',             re.I), 4, "next.js data"),
    (re.compile(r'window\.__NUXT__',          re.I), 4, "nuxt data"),

    # Noscript warnings
    (re.compile(r'you need to enable javascript', re.I), 4, "noscript warning"),
    (re.compile(r'<noscript>.*?javascript',   re.I | re.S), 3, "noscript js required"),

    # React-specific attributes
    (re.compile(r'data-reactroot',            re.I), 4, "react root attr"),
    (re.compile(r'data-react-',               re.I), 3, "react attr"),
]

# ── Static/light signals ──────────────────────────────────────────────────────
STATIC_SIGNALS = [
    (re.compile(r'wp-content|wp-includes',    re.I), 4, "wordpress"),
    (re.compile(r'<p>[\w\s]{20,}',            re.I), 2, "real text in p tags"),
    (re.compile(r'<h[123][^>]*>[\w\s]{5,}',   re.I), 2, "heading with text"),
    (re.compile(r'squarespace',               re.I), 3, "squarespace (SSR)"),
    (re.compile(r'wix\.com',                  re.I), 1, "wix (partially static)"),
    (re.compile(r'shopify',                   re.I), 3, "shopify (SSR)"),
    (re.compile(r'webflow',                   re.I), 3, "webflow (static)"),
]


def classify_html(html: str) -> dict:
    lines = html.split("\n")[:HEAD_LINES]
    snippet = "\n".join(lines)

    js_score  = 0
    js_hits   = []
    for pattern, weight, label in JS_SIGNALS:
        if pattern.search(snippet):
            js_score += weight
            js_hits.append(label)

    static_score = 0
    static_hits  = []
    for pattern, weight, label in STATIC_SIGNALS:
        if pattern.search(snippet):
            static_score += weight
            static_hits.append(label)

    # visible text density (rough)
    text_only = re.sub(r"<[^>]+>", " ", snippet)
    words = len(re.findall(r"\b[a-zA-Z]{3,}\b", text_only))

    if words > 40:
        static_score += 2
        static_hits.append(f"word_density={words}")

    if js_score >= 4:
        verdict = "js_heavy"
    elif js_score >= 2 and static_score < 3:
        verdict = "js_likely"
    elif static_score >= 3:
        verdict = "static"
    else:
        verdict = "unknown"

    return {
        "verdict":      verdict,
        "js_score":     js_score,
        "static_score": static_score,
        "js_signals":   js_hits,
        "static_signals": static_hits,
        "words_in_head": words,
    }


# ── async fetch ───────────────────────────────────────────────────────────────

async def fetch_and_classify(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    url: str,
) -> dict:
    clean = url.strip()
    if not clean:
        return {"url": url, "verdict": "no_url", "error": "empty"}
    if not clean.startswith(("http://", "https://")):
        clean = "https://" + clean

    async with sem:
        try:
            async with session.get(
                clean,
                timeout=aiohttp.ClientTimeout(total=TIMEOUT_S),
                allow_redirects=True,
            ) as resp:
                raw = await resp.content.read(READ_BYTES)
                html = raw.decode("utf-8", errors="ignore")
                result = classify_html(html)
                result["url"] = url
                result["http_status"] = resp.status
                return result

        except asyncio.TimeoutError:
            return {"url": url, "verdict": "timeout", "error": "timeout"}
        except Exception as e:
            # fallback: try http if https failed
            if clean.startswith("https://"):
                try:
                    http_url = clean.replace("https://", "http://", 1)
                    async with session.get(
                        http_url,
                        timeout=aiohttp.ClientTimeout(total=TIMEOUT_S),
                        allow_redirects=True,
                    ) as resp:
                        raw = await resp.content.read(READ_BYTES)
                        html = raw.decode("utf-8", errors="ignore")
                        result = classify_html(html)
                        result["url"] = url
                        result["http_status"] = resp.status
                        return result
                except Exception:
                    pass
            return {"url": url, "verdict": "error", "error": str(e)[:80]}


async def classify_batch(
    urls: list[str],
    concurrency: int = CONCURRENCY,
    progress: bool = True,
) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    results = []
    done = 0
    t0 = time.time()

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [asyncio.create_task(fetch_and_classify(session, sem, url)) for url in urls]
        for coro in asyncio.as_completed(tasks):
            r = await coro
            results.append(r)
            done += 1
            if progress:
                speed = done / max(time.time() - t0, 0.1)
                print(f"  {done}/{len(urls)} | {speed:.1f}/s", end="\r")

    if progress:
        print()

    url_order = {url: i for i, url in enumerate(urls)}
    results.sort(key=lambda r: url_order.get(r["url"], 9999))
    return results


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url",    type=str, default=None)
    parser.add_argument("--csv",    type=str, default=None)
    parser.add_argument("--col",    type=str, default="Company Website")
    parser.add_argument("--sample", type=int, default=None)
    args = parser.parse_args()

    if args.url:
        results = asyncio.run(classify_batch([args.url], progress=False))
        r = results[0]
        print(f"\nURL: {r['url']}")
        print(f"Verdict:       {r['verdict']}")
        print(f"JS score:      {r.get('js_score', '-')}  signals: {r.get('js_signals', [])}")
        print(f"Static score:  {r.get('static_score', '-')}  signals: {r.get('static_signals', [])}")
        print(f"Words in head: {r.get('words_in_head', '-')}")
        if r.get('error'):
            print(f"Error:         {r['error']}")
        return

    if args.csv:
        with open(args.csv, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if args.sample:
            rows = rows[:args.sample]
        urls = [r.get(args.col, "") for r in rows]

        print(f"Checking {len(urls)} URLs...\n")
        t0 = time.time()
        results = asyncio.run(classify_batch(urls))
        elapsed = time.time() - t0

        from collections import Counter
        counts = Counter(r["verdict"] for r in results)
        print(f"\nDone in {elapsed:.1f}s")
        print(f"\nVERDICT BREAKDOWN:")
        for verdict, n in sorted(counts.items(), key=lambda x: -x[1]):
            pct = n / len(results) * 100
            bar = "#" * int(pct / 2)
            print(f"  {verdict:<12} {n:>4}  {pct:>5.1f}%  {bar}")

        print(f"\nSAMPLE — js_heavy:")
        for r in [x for x in results if x["verdict"] in ("js_heavy", "js_likely")][:5]:
            print(f"  {r['url'][:55]:<55}  signals: {r['js_signals']}")

        print(f"\nSAMPLE — static:")
        for r in [x for x in results if x["verdict"] == "static"][:5]:
            print(f"  {r['url'][:55]:<55}  signals: {r['static_signals']}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()

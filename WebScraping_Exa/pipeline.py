"""
pipeline.py — CLI orchestrator: Exa + LLM enrichment pipeline

Modes:
  exa-only    — fetch all URLs via Exa, then run LLM  (default)
  text-only   — use existing text column, skip Exa
  hybrid      — existing text if available, Exa for the rest

Pass 3: low-confidence URLs re-fetched with subpages, LLM re-run.

CLI:
    py pipeline.py --input leads.csv --limit 50
    py pipeline.py --input leads.csv --mode text-only --text-col "ai_summary"
    py pipeline.py --input leads.csv --mode hybrid --text-col "ai_summary" --subpages 5
    py pipeline.py --input leads.csv --output out.csv --cols summary,icp_fit,geography
"""

import asyncio
import argparse
import sys
import time
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from core.exa import fetch_batch, ExaResult
from core.llm import extract_batch, LLMResult, list_prompts, CONFIDENCE_THRESHOLD

URL_KEYWORDS = ["website", "url", "site", "domain", "web", "link"]


def detect_url_col(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        if any(k in col.lower() for k in URL_KEYWORDS):
            return col
    return None


def normalize_url(url: str) -> str:
    url = url.strip()
    if url and not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


def print_section(title: str):
    print(f"\n[{title}]")


def build_output_path(input_path: str) -> str:
    p = Path(input_path)
    return str(p.parent / (p.stem + "_enriched" + p.suffix))


async def run(args) -> None:
    t_total = time.time()

    # ── Load CSV ───────────────────────────────────────────────────────────────
    df = pd.read_csv(args.input)
    total_rows = len(df)

    if args.limit:
        df = df.head(args.limit)
    n = len(df)

    url_col = args.col or detect_url_col(df)
    if not url_col and args.mode != "text-only":
        print(f"ERROR: no URL column found. Use --col to specify one.")
        sys.exit(1)

    text_col = args.text_col
    prompt = args.prompt
    threshold = args.confidence_threshold
    subpages = args.subpages
    output_cols = [c.strip() for c in args.cols.split(",")] if args.cols else None

    print(f"Pipeline start | mode={args.mode} | prompt={prompt} | rows={n}")
    if url_col:
        print(f"URL col: {url_col}")
    if text_col:
        print(f"Text col: {text_col}")

    # ── Build work items ───────────────────────────────────────────────────────
    # items_for_llm: list of {"url": str, "text": str}
    # url → df index map for writing back results
    url_to_idx: dict[str, int] = {}
    exa_urls: list[str] = []
    items_for_llm: list[dict] = []

    for i, (idx, row) in enumerate(df.iterrows()):
        raw_url = str(row.get(url_col, "")).strip() if url_col else ""
        url = normalize_url(raw_url) if raw_url and raw_url != "nan" else f"row_{i}"

        existing_text = ""
        if text_col:
            val = row.get(text_col, "")
            if isinstance(val, str) and val.strip() and val.strip() not in ("nan", "None"):
                existing_text = val.strip()

        url_to_idx[url] = idx

        if args.mode == "text-only":
            if existing_text:
                items_for_llm.append({"url": url, "text": existing_text})
            else:
                # no text — skip
                pass

        elif args.mode == "exa-only":
            if raw_url and raw_url not in ("nan", "None"):
                exa_urls.append(url)
            # no url — skip

        elif args.mode == "hybrid":
            if existing_text:
                items_for_llm.append({"url": url, "text": existing_text})
            elif raw_url and raw_url not in ("nan", "None"):
                exa_urls.append(url)

    # ── Pass 1: Exa fetch ──────────────────────────────────────────────────────
    if exa_urls:
        print_section(f"Pass 1 — Exa fetch: {len(exa_urls)} URLs")
        exa_results = await fetch_batch(exa_urls, concurrency=50, progress=True)

        ok_exa = [r for r in exa_results if r.ok]
        err_exa = [r for r in exa_results if not r.ok]
        print(f"  OK={len(ok_exa)} | Err={len(err_exa)}")
        if err_exa:
            err_types: dict[str, int] = {}
            for r in err_exa:
                k = (r.error or "unknown").split(":")[0]
                err_types[k] = err_types.get(k, 0) + 1
            for k, v in err_types.items():
                print(f"    {k}: {v}")

        for r in ok_exa:
            items_for_llm.append({"url": r.url, "text": r.total_text})

    # ── Pass 2: LLM ───────────────────────────────────────────────────────────
    if not items_for_llm:
        print("No items to process. Check --mode and column names.")
        sys.exit(1)

    print_section(f"Pass 2 — LLM extraction: {len(items_for_llm)} items | prompt={prompt}")
    llm_results = await extract_batch(items_for_llm, prompt_name=prompt,
                                      concurrency=50, progress=True)

    ok_llm = [r for r in llm_results if r.ok]
    low_conf = [r for r in ok_llm if r.confidence < threshold]
    high_conf = [r for r in ok_llm if r.confidence >= threshold]
    print(f"  OK={len(ok_llm)} | high_conf={len(high_conf)} | low_conf={len(low_conf)}")

    # ── Pass 3: subpages retry ────────────────────────────────────────────────
    retry_map: dict[str, LLMResult] = {}
    if low_conf and subpages > 0:
        retry_urls = [r.url for r in low_conf if not r.url.startswith("row_")]
        if retry_urls:
            print_section(f"Pass 3 — Subpages retry: {len(retry_urls)} URLs | subpages={subpages}")
            retry_exa = await fetch_batch(retry_urls, concurrency=50,
                                          subpages=subpages, progress=True)
            retry_items = [
                {"url": r.url, "text": r.total_text}
                for r in retry_exa if r.ok
            ]
            if retry_items:
                retry_llm = await extract_batch(retry_items, prompt_name=prompt,
                                                concurrency=50, progress=True)
                improved = 0
                for r in retry_llm:
                    if r.ok and r.confidence >= threshold:
                        improved += 1
                    retry_map[r.url] = r
                print(f"  Retried={len(retry_llm)} | improved={improved}")

    # ── Merge results into DataFrame ──────────────────────────────────────────
    # Final results map: url → LLMResult (retry takes priority if exists)
    final_results: dict[str, LLMResult] = {}
    for r in llm_results:
        if r.ok:
            final_results[r.url] = r
    for url, r in retry_map.items():
        if r.ok:
            final_results[url] = r

    # Determine which output columns to write
    all_keys: set[str] = set()
    for r in final_results.values():
        all_keys.update(r.data.keys())
    all_keys.discard("raw")

    if output_cols:
        write_keys = [k for k in output_cols if k in all_keys]
        missing = [k for k in output_cols if k not in all_keys]
        if missing:
            print(f"  Warning: requested cols not found in LLM output: {missing}")
    else:
        write_keys = sorted(all_keys)

    # Rename colliding columns if --overwrite not set
    col_map: dict[str, str] = {}
    for key in write_keys:
        if key in df.columns and not args.overwrite:
            col_map[key] = key + "_llm"
        else:
            col_map[key] = key

    # Initialize new columns
    for out_col in col_map.values():
        if out_col not in df.columns:
            df[out_col] = None

    # Write results
    for url, result in final_results.items():
        if url not in url_to_idx:
            continue
        idx = url_to_idx[url]
        for key in write_keys:
            out_col = col_map[key]
            val = result.data.get(key)
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            df.at[idx, out_col] = val

    # ── Save ──────────────────────────────────────────────────────────────────
    output_path = args.output or build_output_path(args.input)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = time.time() - t_total
    processed = len(items_for_llm)
    success = len(final_results)
    pass3_count = len(retry_map)
    pass3_improved = sum(1 for r in retry_map.values() if r.ok and r.confidence >= threshold)

    exa_pages_fetched = len(exa_urls)
    subpages_fetched = pass3_count * subpages if pass3_count else 0
    exa_cost = (exa_pages_fetched + subpages_fetched) * 0.001
    llm_cost_est = processed * 0.00015  # rough estimate

    print("\n" + "=" * 60)
    print(f"Mode:       {args.mode}")
    print(f"Prompt:     {prompt}")
    print(f"Total rows: {n}")
    print(f"Processed:  {processed}")
    print(f"Success:    {success} ({success/n*100:.1f}%)")
    if pass3_count:
        print(f"Pass 3:     {pass3_count} retried, {pass3_improved} improved")
    print(f"Time:       {elapsed:.1f}s ({n/elapsed:.1f} leads/sec)")
    print(f"Exa cost:   ~${exa_cost:.3f} ({exa_pages_fetched} pages + {subpages_fetched} subpages)")
    print(f"LLM cost:   ~${llm_cost_est:.3f}")
    print(f"Saved to:   {output_path}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Exa + LLM enrichment pipeline")
    parser.add_argument("--input",    required=True,   help="Input CSV path")
    parser.add_argument("--output",   default=None,    help="Output CSV path (default: input_enriched.csv)")
    parser.add_argument("--col",      default=None,    help="URL column name (auto-detected if not set)")
    parser.add_argument("--text-col", default=None,    help="Existing text column to use instead of Exa")
    parser.add_argument("--limit",    type=int, default=0,   help="Process only first N rows (0 = all)")
    parser.add_argument("--mode",     default="exa-only",
                        choices=["exa-only", "text-only", "hybrid"],
                        help="Pipeline mode: exa-only | text-only | hybrid")
    parser.add_argument("--prompt",   default="company_full",
                        help=f"Prompt name. Available: {list_prompts()}")
    parser.add_argument("--cols",     default=None,
                        help="Comma-separated output columns to save (default: all LLM fields)")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing columns instead of adding _llm suffix")
    parser.add_argument("--confidence-threshold", type=int, default=CONFIDENCE_THRESHOLD,
                        help=f"Below this confidence → Pass 3 retry (default: {CONFIDENCE_THRESHOLD})")
    parser.add_argument("--subpages", type=int, default=0,
                        help="Subpages to fetch in Pass 3 (0 = skip Pass 3)")
    args = parser.parse_args()

    if not args.limit:
        args.limit = None

    asyncio.run(run(args))


if __name__ == "__main__":
    main()

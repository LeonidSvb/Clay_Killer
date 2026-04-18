import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', 'upwork-pipeline', '.env'))

from db.client import get_existing_post_ids, save_signals
from notifications.telegram import notify_pending
from pipeline.scraper import load_config, load_cookies, make_headers, make_api_headers, scrape_category
from pipeline.classify import classify_post, load_prompt


def run_pipeline():
    cfg = load_config()
    api_key = cfg.get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("ERROR: set openrouter_api_key in config.json or OPENROUTER_API_KEY env var")
        sys.exit(1)

    model = cfg.get("classify_model", "google/gemini-2.5-flash-lite")
    hours = cfg.get("hours_back", 15)
    cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=hours)

    print(f"[run] Skool pipeline — cutoff {cutoff_dt.strftime('%Y-%m-%d %H:%M')} UTC ({hours}h)")

    # Scrape
    cookies = load_cookies(cfg["cookies_file"])
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    headers = make_headers(cookie_str)
    api_headers = make_api_headers(cookie_str)

    all_posts = {}
    categories = {cid: cat for cid, cat in cfg["categories"].items() if cat.get("scrape")}
    for cid, cat in categories.items():
        posts = scrape_category(
            cfg["community"], cid, cat["name"], cutoff_dt,
            headers, api_headers, cfg
        )
        for p in posts:
            all_posts[p["id"]] = p

    print(f"[run] Scraped {len(all_posts)} posts total")
    if not all_posts:
        print("[run] Nothing to classify")
        return

    # Dedup against DB
    existing_ids = get_existing_post_ids()
    new_posts = [p for pid, p in all_posts.items() if pid not in existing_ids]
    print(f"[run] {len(new_posts)} new posts (skipping {len(all_posts) - len(new_posts)} already in DB)")

    if not new_posts:
        print("[run] All posts already processed")
        notify_pending()
        return

    # Classify
    prompt_template = load_prompt()
    results = []
    signal_count = 0
    error_count = 0

    for i, post in enumerate(new_posts):
        print(f"  [{i+1}/{len(new_posts)}] {post.get('category','?')} | {post.get('title','')[:60]}", end=" -> ", flush=True)
        try:
            result = classify_post(post, prompt_template, api_key, model)
        except Exception as e:
            print(f"ERROR: {e}")
            error_count += 1
            time.sleep(2)
            continue

        is_signal = result.get("is_signal", False)
        confidence = result.get("confidence", "low")
        print(f"{'SIGNAL' if is_signal else 'skip'} [{confidence}]")

        record = {
            "post_id": post["id"],
            "post_url": post.get("url", ""),
            "post_title": post.get("title", ""),
            "category": post.get("category", ""),
            "created_at": post.get("created_at") or None,
            "is_signal": is_signal,
            "confidence": confidence,
            "signal_type": result.get("signal_type"),
            "signal_text": result.get("signal_text"),
            "reason": result.get("reason"),
            "contact": result.get("contact"),
            "community": cfg.get("community"),
        }
        results.append(record)
        if is_signal:
            signal_count += 1

        time.sleep(0.5)

    # Save to DB
    saved = save_signals(results)
    print(f"[run] Saved {saved} records to DB | signals: {signal_count} | errors: {error_count}")

    # Notify
    sent = notify_pending()
    print(f"[run] Notified {sent} signals via Telegram")


if __name__ == "__main__":
    run_pipeline()

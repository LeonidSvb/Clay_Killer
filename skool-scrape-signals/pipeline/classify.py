import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path


OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-flash-1.5"
DELAY = 0.5


def load_config():
    with open("config.json") as f:
        return json.load(f)


def load_prompt():
    prompt_path = Path(__file__).parent.parent / "prompts" / "classify.txt"
    with open(prompt_path, encoding="utf-8") as f:
        return f.read()


def build_post_payload(post):
    payload = {
        "id": post["id"],
        "category": post["category"],
        "title": post.get("title", ""),
        "content": post.get("content", ""),
        "url": post.get("url", ""),
        "author": {
            "name": post.get("author", {}).get("name", ""),
            "id": post.get("author", {}).get("id", ""),
            "linkedin": post.get("author", {}).get("linkedin", ""),
        },
        "comments": [],
    }
    for c in post.get("comments", [])[:20]:
        payload["comments"].append({
            "author": c.get("author", {}).get("name", ""),
            "author_id": c.get("author", {}).get("id", ""),
            "author_linkedin": c.get("author", {}).get("linkedin", ""),
            "content": c.get("content", ""),
            "replies": [
                {
                    "author": r.get("author", {}).get("name", ""),
                    "author_id": r.get("author", {}).get("id", ""),
                    "content": r.get("content", ""),
                }
                for r in c.get("replies", [])[:5]
            ],
        })
    return payload


def classify_post(post, prompt_template, api_key, model):
    post_json = json.dumps(build_post_payload(post), ensure_ascii=False)
    prompt = prompt_template.replace("{{POST_JSON}}", post_json)

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 400,
    }).encode("utf-8")

    req = urllib.request.Request(
        OPENROUTER_API,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/skool-scrape-signals",
            "X-Title": "Skool Signal Classifier",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_err = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code}: {body_err[:200]}")

    content = data["choices"][0]["message"]["content"].strip()

    # Strip markdown code fences if present
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    return json.loads(content)


def load_existing_leads(output_path):
    if not output_path.exists():
        return {}
    with open(output_path, encoding="utf-8") as f:
        data = json.load(f)
    return {item["post_id"]: item for item in data}


def main():
    cfg = load_config()
    api_key = cfg.get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("ERROR: set openrouter_api_key in config.json or OPENROUTER_API_KEY env var")
        sys.exit(1)

    model = cfg.get("classify_model", DEFAULT_MODEL)

    # Determine posts file
    if len(sys.argv) > 1:
        posts_file = Path(sys.argv[1])
    else:
        output_dir = Path(cfg["output_dir"])
        files = sorted(output_dir.glob("posts_*.json"), reverse=True)
        if not files:
            print("No posts_*.json files found in data/")
            sys.exit(1)
        posts_file = files[0]

    today = datetime.now().strftime("%Y-%m-%d")
    leads_file = Path(cfg["output_dir"]) / f"leads_{today}.json"
    all_results_file = Path(cfg["output_dir"]) / f"classify_all_{today}.json"

    print(f"Classify Skool posts -> leads")
    print(f"Input  : {posts_file}")
    print(f"Model  : {model}")
    print(f"Leads  : {leads_file}")

    with open(posts_file, encoding="utf-8") as f:
        posts = json.load(f)

    print(f"Posts  : {len(posts)}")

    prompt_template = load_prompt()

    # Load existing results to resume
    existing_leads = load_existing_leads(leads_file)
    all_results_path = Path(cfg["output_dir"]) / f"classify_all_{today}.json"
    existing_all = {}
    if all_results_path.exists():
        with open(all_results_path, encoding="utf-8") as f:
            for item in json.load(f):
                existing_all[item["post_id"]] = item

    leads = dict(existing_leads)
    all_results = dict(existing_all)

    skip_count = 0
    signal_count = 0
    error_count = 0

    for i, post in enumerate(posts):
        post_id = post["id"]

        if post_id in all_results:
            skip_count += 1
            if all_results[post_id].get("is_signal"):
                signal_count += 1
            continue

        print(f"  [{i+1}/{len(posts)}] {post.get('category','?')} | {post.get('title','')[:60]}", end=" -> ", flush=True)

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
            "post_id": post_id,
            "post_url": post.get("url", ""),
            "post_title": post.get("title", ""),
            "category": post.get("category", ""),
            "created_at": post.get("created_at", ""),
            "is_signal": is_signal,
            "confidence": confidence,
            "signal_type": result.get("signal_type"),
            "signal_text": result.get("signal_text"),
            "reason": result.get("reason"),
            "contact": result.get("contact"),
        }
        all_results[post_id] = record

        if is_signal:
            signal_count += 1
            leads[post_id] = record

        # Save progress every 10 posts
        if (i + 1) % 10 == 0:
            _save(leads_file, list(leads.values()))
            _save(all_results_path, list(all_results.values()))

        time.sleep(DELAY)

    _save(leads_file, list(leads.values()))
    _save(all_results_path, list(all_results.values()))

    total_processed = len(posts) - skip_count
    print(f"\nDone.")
    print(f"  Processed : {total_processed} (skipped {skip_count} cached)")
    print(f"  Signals   : {signal_count}")
    print(f"  Errors    : {error_count}")
    print(f"  Leads file: {leads_file}")

    if leads:
        print(f"\nTop signals:")
        by_confidence = sorted(leads.values(), key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.get("confidence", "low"), 3))
        for lead in by_confidence[:10]:
            contact = lead.get("contact") or {}
            print(f"  [{lead.get('confidence','?')}] {lead.get('signal_type','?')} | {contact.get('name','?')} | {lead.get('post_url','')}")


def _save(path, data):
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

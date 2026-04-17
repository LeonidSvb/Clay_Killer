import json
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path


def load_config():
    with open("config.json") as f:
        return json.load(f)


def load_cookies(path):
    with open(path) as f:
        raw = json.load(f)
    return {c["name"]: c["value"] for c in raw if "name" in c and "value" in c}


def make_headers(cookie_str):
    return {
        "Cookie": cookie_str,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://www.skool.com/",
    }


def make_api_headers(cookie_str):
    return {
        "Cookie": cookie_str,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
        "Accept": "application/json",
        "Referer": "https://www.skool.com/",
    }


def fetch_page(community, category_id, page, headers, cfg):
    sort = cfg.get("sort", "newest")
    url = f"https://www.skool.com/{community}?c={category_id}&s={sort}&fl=&p={page}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} on page {page}")
        return []

    match = re.search(r'__NEXT_DATA__[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        return []

    try:
        data = json.loads(match.group(1))
        return data["props"]["pageProps"].get("postTrees", [])
    except (json.JSONDecodeError, KeyError):
        return []


def fetch_comments(post_id, group_id, api_headers):
    url = f"https://api2.skool.com/posts/{post_id}/comments?group-id={group_id}&limit=30"
    req = urllib.request.Request(url, headers=api_headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception:
        return []

    comments = []
    children = data.get("post_tree", {}).get("children", [])
    for child in children:
        post = child.get("post", {})
        meta = post.get("metadata", {})
        user = post.get("user", {})
        user_meta = user.get("metadata", {})
        comment = {
            "id": post.get("id", ""),
            "content": meta.get("content", ""),
            "created_at": post.get("created_at", ""),
            "upvotes": meta.get("upvotes", 0),
            "author": {
                "name": f"{user.get('firstName', user.get('first_name', ''))} {user.get('lastName', user.get('last_name', ''))}".strip(),
                "id": user.get("id", ""),
                "linkedin": user_meta.get("linkLinkedin", user_meta.get("link_linkedin", "")),
                "website": user_meta.get("linkWebsite", user_meta.get("link_website", "")),
                "bio": user_meta.get("bio", "")[:200],
            },
            "replies": [],
        }
        for reply_child in child.get("children", []):
            rp = reply_child.get("post", {})
            rm = rp.get("metadata", {})
            ru = rp.get("user", {})
            rum = ru.get("metadata", {})
            comment["replies"].append({
                "id": rp.get("id", ""),
                "content": rm.get("content", ""),
                "created_at": rp.get("created_at", ""),
                "author": {
                    "name": f"{ru.get('firstName', ru.get('first_name', ''))} {ru.get('lastName', ru.get('last_name', ''))}".strip(),
                    "id": ru.get("id", ""),
                    "linkedin": rum.get("linkLinkedin", rum.get("link_linkedin", "")),
                },
            })
        comments.append(comment)
    return comments


def parse_post(tree, category_name):
    post = tree.get("post", tree)
    meta = post.get("metadata", {})
    user = post.get("user", {})
    user_meta = user.get("metadata", {})

    return {
        "id": post.get("id", ""),
        "category": category_name,
        "title": meta.get("title", ""),
        "content": meta.get("content", "")[:500],
        "upvotes": meta.get("upvotes", 0),
        "comments_count": meta.get("comments", 0),
        "created_at": post.get("createdAt", ""),
        "url": post.get("url", ""),
        "author": {
            "name": f"{user.get('firstName', '')} {user.get('lastName', '')}".strip(),
            "id": user.get("id", ""),
            "linkedin": user_meta.get("linkLinkedin", ""),
            "website": user_meta.get("linkWebsite", ""),
            "bio": user_meta.get("bio", "")[:200],
        },
        "comments": [],
    }


def scrape_category(community, category_id, category_name, cutoff_dt, headers, api_headers, cfg):
    print(f"\n  [{category_name}]")
    posts = []
    seen_ids = set()

    for page in range(1, 50):
        trees = fetch_page(community, category_id, page, headers, cfg)
        if not trees:
            print(f"    page {page}: empty, stopping")
            break

        new_this_page = 0
        stop = False
        for tree in trees:
            post = tree.get("post", tree)
            created_str = post.get("createdAt", "")
            post_id = post.get("id", "")

            if not created_str:
                continue

            try:
                created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            except ValueError:
                continue

            if created_dt < cutoff_dt:
                stop = True
                break

            if post_id in seen_ids:
                continue
            seen_ids.add(post_id)

            posts.append(parse_post(tree, category_name))
            new_this_page += 1

        print(f"    page {page}: +{new_this_page} posts")
        if stop:
            print(f"    reached cutoff, stopping")
            break

        time.sleep(cfg["request_delay"])

    if cfg.get("fetch_comments"):
        min_count = cfg.get("fetch_comments_min_count", 1)
        posts_with_comments = [p for p in posts if p["comments_count"] >= min_count]
        print(f"    fetching comments for {len(posts_with_comments)}/{len(posts)} posts...")
        for p in posts_with_comments:
            p["comments"] = fetch_comments(p["id"], cfg["group_id"], api_headers)
            time.sleep(cfg["request_delay"])

    return posts


def load_existing(output_path):
    if not output_path.exists():
        return {}
    with open(output_path, encoding="utf-8") as f:
        existing = json.load(f)
    return {p["id"]: p for p in existing}


def main():
    cfg = load_config()
    cookies = load_cookies(cfg["cookies_file"])
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    headers = make_headers(cookie_str)
    api_headers = make_api_headers(cookie_str)

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=cfg["days_back"])
    today = datetime.now().strftime("%Y-%m-%d")
    output_path = Path(cfg["output_dir"]) / f"posts_{today}.json"

    print(f"Skool signal scraper")
    print(f"Community : {cfg['community']}")
    print(f"Cutoff    : {cutoff_dt.strftime('%Y-%m-%d %H:%M')} UTC ({cfg['days_back']} days)")
    print(f"Comments  : {'yes (>=' + str(cfg.get('fetch_comments_min_count',1)) + ' comments)' if cfg.get('fetch_comments') else 'no'}")
    print(f"Output    : {output_path}")

    existing = load_existing(output_path)
    all_posts = dict(existing)

    categories = {cid: cat for cid, cat in cfg["categories"].items() if cat.get("scrape")}

    for cid, cat in categories.items():
        new_posts = scrape_category(
            cfg["community"], cid, cat["name"], cutoff_dt,
            headers, api_headers, cfg
        )
        added = 0
        for p in new_posts:
            if p["id"] not in all_posts:
                all_posts[p["id"]] = p
                added += 1
        print(f"    -> {added} new")

    result = sorted(all_posts.values(), key=lambda x: x["created_at"], reverse=True)

    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nTotal: {len(result)} posts saved to {output_path}")

    # summary
    total_comments = sum(len(p.get("comments", [])) for p in result)
    by_category = {}
    for p in result:
        by_category[p["category"]] = by_category.get(p["category"], 0) + 1
    print("\nBy category:")
    for cat, count in sorted(by_category.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")
    print(f"Total comments fetched: {total_comments}")


if __name__ == "__main__":
    main()

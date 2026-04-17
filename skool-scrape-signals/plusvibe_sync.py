import json
import time
from datetime import datetime, timezone
from pathlib import Path

from curl_cffi import requests

BASE = "https://api.pipl.ai/v1"
COOKIES_FILE = "plusvibe_cookies.json"
OUTPUT_DIR = Path("data")

POSITIVE_LABELS = {"Interested", "Meeting Booked", "Meeting Cancelled", "Meeting Completed", "Positive", "Neitral"}
EXCLUDE_LABELS  = {"Not Interested", "Out of Office", "Automatic Reply", "Unsubscribe", "Wrong Person", "Not Qualified", "Loose interest"}


def load_refresh_token():
    with open(COOKIES_FILE) as f:
        cookies = json.load(f)
    token_map = {c["name"]: c["value"] for c in cookies}
    workspace_id = token_map.get("workspaceSelected", "")
    refresh_token = token_map.get("refreshToken", "")
    return refresh_token, workspace_id


def get_auth_token(refresh_token):
    resp = requests.post(
        f"{BASE}/auth/refresh-token",
        json={"refresh_token": refresh_token},
        impersonate="chrome124"
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 1:
        raise RuntimeError(f"Token refresh failed: {data.get('message')}")
    return data["data"]["access_token"]


def fetch_all_threads(token, workspace_id):
    headers = {"Authorization": f"Bearer {token}", "workspace-id": workspace_id}
    all_threads = []
    page = 1

    while True:
        resp = requests.get(
            f"{BASE}/inbox",
            params={"page": page, "limit": 50},
            headers=headers,
            impersonate="chrome124"
        )
        resp.raise_for_status()
        batch = resp.json().get("data", [])
        if not batch:
            break
        all_threads.extend(batch)
        print(f"  page {page}: +{len(batch)} threads (total {len(all_threads)})")
        if len(batch) < 50:
            break
        page += 1
        time.sleep(0.5)

    return all_threads


def parse_thread(t):
    return {
        "id": t.get("_id", ""),
        "thread_id": t.get("thread_id", ""),
        "from": t.get("from", ""),
        "from_email": t.get("from_email", ""),
        "to": t.get("to", ""),
        "subject": t.get("subject", ""),
        "snippet": t.get("snippet", "")[:500],
        "direction": t.get("direction", ""),
        "label": t.get("lead_label_txt", ""),
        "label_icon": t.get("lead_label_icon", ""),
        "thread_status": t.get("thread_status", ""),
        "is_read": t.get("is_read", 0),
        "is_star": t.get("is_star", 0),
        "modified_at": t.get("thread_modified_at", ""),
        "camp_id": t.get("camp_id", ""),
        "camp_name": t.get("camp_name", ""),
        "lead_id": t.get("lead_id", ""),
        "lead_first_name": t.get("lead_first_name", ""),
        "lead_last_name": t.get("lead_last_name", ""),
        "lead_email": t.get("lead_email", ""),
    }


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    output_all     = OUTPUT_DIR / f"plusvibe_all_{today}.json"
    output_positive = OUTPUT_DIR / f"plusvibe_positive_{today}.json"

    print("Plusvibe Unibox sync")
    refresh_token, workspace_id = load_refresh_token()
    print(f"Workspace: {workspace_id}")

    print("Refreshing auth token...")
    token = get_auth_token(refresh_token)
    print("Token OK")

    print("\nFetching all threads...")
    threads = fetch_all_threads(token, workspace_id)
    print(f"\nTotal fetched: {len(threads)}")

    parsed = [parse_thread(t) for t in threads]

    positive = [p for p in parsed if p["label"] in POSITIVE_LABELS]
    excluded = [p for p in parsed if p["label"] in EXCLUDE_LABELS]
    other    = [p for p in parsed if p["label"] not in POSITIVE_LABELS and p["label"] not in EXCLUDE_LABELS]

    print(f"\nPositive (keep): {len(positive)}")
    print(f"Excluded (noise): {len(excluded)}")
    print(f"Other/unlabeled: {len(other)}")

    label_counts = {}
    for p in parsed:
        label_counts[p["label"]] = label_counts.get(p["label"], 0) + 1
    print("\nAll labels:")
    for label, count in sorted(label_counts.items(), key=lambda x: -x[1]):
        print(f"  {label or '(no label)'}: {count}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(output_all, "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)
    with open(output_positive, "w", encoding="utf-8") as f:
        json.dump(positive, f, ensure_ascii=False, indent=2)

    print(f"\nSaved:")
    print(f"  All threads   -> {output_all}")
    print(f"  Positive only -> {output_positive}")


if __name__ == "__main__":
    main()

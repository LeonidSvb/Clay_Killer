"""
app/utils/plusvibe_api.py — PlusVibe API client for pushing lead variables.

Uses POST /lead/data/update with 5 concurrent workers + rate limiter (5 req/sec).
"""

import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

PLUSVIBE_SOURCE_COLS = {
    "email", "first_name", "last_name", "job_title", "company_name",
    "company_website", "linkedin_person_url", "phone_number", "city",
    "country", "mx", "status", "label", "sent_step", "total_steps",
    "replied_count", "opened_count", "notes",
    "company_linkedin", "linkedin_url_apollo", "employees_count",
    "industry", "keywords", "company_revenue", "company_short_description",
}

PLUSVIBE_NATIVE_FIELDS = {
    "first_name", "last_name", "job_title", "company_name",
    "company_website", "phone_number", "linkedin_person_url",
    "linkedin_company_url", "city", "country", "state",
    "address_line", "country_code", "department", "industry", "notes",
}

_WORKERS = 5
_MIN_INTERVAL = 1.0 / _WORKERS  # 200ms between dispatches to stay under 5 req/sec


def update_lead_variables(
    email: str,
    variables: dict,
    api_key: str,
    workspace_id: str,
    base_url: str = "https://api.plusvibe.ai/api/v1",
) -> dict:
    """
    Update lead variables in PlusVibe.
    Native field keys update the lead object; unknown keys become custom variables.
    Returns {"ok": True} or {"ok": False, "error": str}.
    """
    try:
        resp = requests.post(
            f"{base_url}/lead/data/update",
            headers={"x-api-key": api_key},
            json={"workspace_id": workspace_id, "email": email, "variables": variables},
            timeout=15,
        )
        if resp.status_code == 200:
            return {"ok": True}
        return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def push_leads_batch(
    rows: list[dict],
    col_map: dict[str, str],
    api_key: str,
    workspace_id: str,
    progress_queue: queue.Queue,
    stop_event,
    base_url: str = "https://api.plusvibe.ai/api/v1",
) -> list[dict]:
    """
    Push variables for a batch of leads using 5 concurrent workers.

    rows: list of dicts, each must have "email" key + columns from col_map
    col_map: {df_col_name: plusvibe_variable_key}
    progress_queue: receives {"done", "total", "errors"} dicts
    stop_event: threading.Event — set to stop early
    """
    total = len(rows)
    results = [None] * total
    lock = threading.Lock()
    done_count = [0]
    error_count = [0]

    def process(i: int, row: dict):
        if stop_event.is_set():
            results[i] = {"email": row.get("email", ""), "ok": False, "error": "stopped"}
            with lock:
                done_count[0] += 1
                error_count[0] += 1
                progress_queue.put({"done": done_count[0], "total": total, "errors": error_count[0]})
            return

        email = str(row.get("email", "")).strip()
        if not email:
            results[i] = {"email": "", "ok": False, "error": "empty email"}
            with lock:
                done_count[0] += 1
                error_count[0] += 1
                progress_queue.put({"done": done_count[0], "total": total, "errors": error_count[0]})
            return

        variables = {}
        for df_col, pv_key in col_map.items():
            val = row.get(df_col)
            if val is not None and str(val).strip() not in ("", "nan", "None", "null"):
                variables[pv_key] = str(val).strip()

        if not variables:
            results[i] = {"email": email, "ok": True, "error": None}
            with lock:
                done_count[0] += 1
                progress_queue.put({"done": done_count[0], "total": total, "errors": error_count[0]})
            return

        result = update_lead_variables(email, variables, api_key, workspace_id, base_url)
        result["email"] = email
        results[i] = result
        with lock:
            done_count[0] += 1
            if not result["ok"]:
                error_count[0] += 1
            progress_queue.put({"done": done_count[0], "total": total, "errors": error_count[0]})

    with ThreadPoolExecutor(max_workers=_WORKERS) as executor:
        futures = []
        for i, row in enumerate(rows):
            if stop_event.is_set():
                break
            futures.append(executor.submit(process, i, row))
            time.sleep(_MIN_INTERVAL)  # throttle dispatch to ~5 req/sec

        for f in as_completed(futures):
            f.result()

    return [r for r in results if r is not None]

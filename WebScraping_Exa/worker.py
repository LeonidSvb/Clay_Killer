"""
worker.py — Background enrichment worker.

Picks up pending tasks from DB, runs enrichment, saves results in batches.
Started automatically by run.bat alongside Streamlit.

Usage:
    py worker.py
"""

import sys
import os
import time
import queue
import threading
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env", override=True)

Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/worker.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("worker")

BATCH_SAVE_SIZE = 100


# ---------------------------------------------------------------------------
# Result saving
# ---------------------------------------------------------------------------

def _save_batch(workspace_id: int, leads: list, results: list, output_col: str) -> None:
    from core.db import save_enrichment_batch
    rows_to_save = []
    for r in results:
        if not r.get("ok") or not r.get("data"):
            continue
        idx = r["idx"]
        if idx >= len(leads):
            continue
        email = leads[idx]["email"]
        rows_to_save.append({"email": email, "data": r["data"]})
    if rows_to_save:
        save_enrichment_batch(workspace_id, rows_to_save)


# ---------------------------------------------------------------------------
# LLM enrichment
# ---------------------------------------------------------------------------

def _run_llm(task_id: int, workspace_id: int, leads: list, payload: dict) -> None:
    from app.enrichments.llm import run_llm_enrichment
    from core.tasks import update_task_progress, complete_task, fail_task

    df = _leads_to_df(leads)
    row_indices = _get_row_indices(leads, payload)
    output_col = payload.get("output_col", "result")

    pq: queue.Queue = queue.Queue()
    se = threading.Event()
    results_holder: list = []

    thread = threading.Thread(
        target=lambda: results_holder.extend(
            run_llm_enrichment(
                df=df,
                prompt_text=payload["prompt_text"],
                row_indices=row_indices,
                concurrency=payload.get("concurrency", 50),
                progress_queue=pq,
                stop_event=se,
                api_key=os.getenv("OPENROUTER_API_KEY", ""),
                output_type=payload.get("output_type", "Text"),
                output_config=payload.get("output_config"),
            )
        ),
        daemon=True,
    )
    thread.start()

    last_saved = 0
    while thread.is_alive():
        _drain_queue(pq)
        count = len(results_holder)
        if count - last_saved >= BATCH_SAVE_SIZE:
            _save_batch(workspace_id, leads, results_holder[last_saved:count], output_col)
            last_saved = count
            errors = sum(1 for r in results_holder[:count] if not r["ok"])
            update_task_progress(task_id, count, errors)
        time.sleep(0.5)

    thread.join()

    if last_saved < len(results_holder):
        _save_batch(workspace_id, leads, results_holder[last_saved:], output_col)

    ok = sum(1 for r in results_holder if r["ok"])
    errors = len(results_holder) - ok
    update_task_progress(task_id, len(results_holder), errors)
    complete_task(task_id)
    log.info(f"Task {task_id} LLM done: {ok}/{len(results_holder)} ok, {errors} errors")


# ---------------------------------------------------------------------------
# MX enrichment
# ---------------------------------------------------------------------------

def _run_mx(task_id: int, workspace_id: int, leads: list, payload: dict) -> None:
    from app.enrichments.mx import run_mx_enrichment
    from core.tasks import update_task_progress, complete_task

    df = _leads_to_df(leads)
    row_indices = _get_row_indices(leads, payload)
    email_col = payload.get("email_col", "email")

    pq: queue.Queue = queue.Queue()
    se = threading.Event()
    results_holder: list = []

    thread = threading.Thread(
        target=lambda: results_holder.extend(
            run_mx_enrichment(
                df=df,
                email_col=email_col,
                row_indices=row_indices,
                concurrency=payload.get("concurrency", 60),
                progress_queue=pq,
                stop_event=se,
            )
        ),
        daemon=True,
    )
    thread.start()

    last_saved = 0
    while thread.is_alive():
        _drain_queue(pq)
        count = len(results_holder)
        if count - last_saved >= BATCH_SAVE_SIZE:
            normalized = _normalize_mx(results_holder[last_saved:count])
            _save_batch(workspace_id, leads, normalized, "mx_provider")
            last_saved = count
            update_task_progress(task_id, count)
        time.sleep(0.5)

    thread.join()

    if last_saved < len(results_holder):
        normalized = _normalize_mx(results_holder[last_saved:])
        _save_batch(workspace_id, leads, normalized, "mx_provider")

    ok = sum(1 for r in results_holder if r["ok"])
    errors = len(results_holder) - ok
    update_task_progress(task_id, len(results_holder), errors)
    complete_task(task_id)
    log.info(f"Task {task_id} MX done: {ok}/{len(results_holder)} ok, {errors} errors")


# ---------------------------------------------------------------------------
# Exa enrichment
# ---------------------------------------------------------------------------

def _run_exa(task_id: int, workspace_id: int, leads: list, payload: dict) -> None:
    from app.enrichments.exa import run_exa_enrichment
    from core.tasks import update_task_progress, complete_task

    df = _leads_to_df(leads)
    row_indices = _get_row_indices(leads, payload)
    cfg = payload.get("cfg", {"mode": "summary"})
    output_col = payload.get("output_col", "Website Summary")

    pq: queue.Queue = queue.Queue()
    se = threading.Event()
    results_holder: list = []
    skipped_holder: list = [0]

    def _worker():
        results, skipped = run_exa_enrichment(
            df=df,
            url_col=payload.get("url_col", "Company Website"),
            row_indices=row_indices,
            cfg=cfg,
            concurrency=payload.get("concurrency", 50),
            progress_queue=pq,
            stop_event=se,
            api_key=os.getenv("EXA_API_KEY", ""),
        )
        results_holder.extend(results)
        skipped_holder[0] = skipped

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    last_saved = 0
    while thread.is_alive():
        _drain_queue(pq)
        count = len(results_holder)
        if count - last_saved >= BATCH_SAVE_SIZE:
            _save_batch(workspace_id, leads, results_holder[last_saved:count], output_col)
            last_saved = count
            errors = sum(1 for r in results_holder[:count] if not r["ok"])
            update_task_progress(task_id, count, errors)
        time.sleep(0.5)

    thread.join()

    if last_saved < len(results_holder):
        _save_batch(workspace_id, leads, results_holder[last_saved:], output_col)

    ok = sum(1 for r in results_holder if r["ok"])
    errors = len(results_holder) - ok
    update_task_progress(task_id, len(results_holder), errors)
    complete_task(task_id)
    log.info(
        f"Task {task_id} Exa done: {ok}/{len(results_holder)} ok, "
        f"{errors} errors, {skipped_holder[0]} skipped (empty URL)"
    )


def _run_plusvibe_push(task_id: int, payload: dict) -> None:
    from app.utils.plusvibe_api import push_leads_batch
    from core.tasks import update_task_progress, complete_task, fail_task

    rows = payload.get("rows", [])
    col_map = payload.get("col_map", {})
    api_key = payload.get("api_key") or os.getenv("PLUSVIBE_API_KEY", "")
    pv_workspace_id = payload.get("workspace_id") or os.getenv("PLUSVIBE_WORKSPACE_ID", "")
    base_url = payload.get("base_url") or os.getenv("PLUSVIBE_BASE_URL", "https://api.plusvibe.ai/api/v1")

    if not rows or not col_map:
        log.warning(f"Task {task_id}: empty rows or col_map")
        complete_task(task_id)
        return

    pq: queue.Queue = queue.Queue()
    se = threading.Event()
    results_holder: list = []

    thread = threading.Thread(
        target=lambda: results_holder.extend(
            push_leads_batch(rows, col_map, api_key, pv_workspace_id, pq, se, base_url)
        ),
        daemon=True,
    )
    thread.start()

    while thread.is_alive():
        _drain_queue(pq)
        done = len(results_holder)
        errors = sum(1 for r in results_holder if not r.get("ok"))
        update_task_progress(task_id, done, errors)
        time.sleep(1)

    thread.join()
    ok = sum(1 for r in results_holder if r.get("ok"))
    errors = len(results_holder) - ok
    update_task_progress(task_id, len(results_holder), errors)
    complete_task(task_id)
    log.info(f"Task {task_id} PlusVibe push done: {ok}/{len(results_holder)} ok, {errors} errors")


def _normalize_mx(results: list) -> list:
    out = []
    for r in results:
        if r.get("ok"):
            out.append({
                "idx": r["idx"],
                "ok": True,
                "data": {
                    "mx_provider": r.get("mx_provider", ""),
                    "mx_real": r.get("mx_real", ""),
                },
            })
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _leads_to_df(leads: list):
    import pandas as pd
    rows = []
    for lead in leads:
        row = {k: v for k, v in lead.items() if k not in ("enrichment_data", "wl_id")}
        enrichment = lead.get("enrichment_data") or {}
        if isinstance(enrichment, dict):
            row.update(enrichment)
        rows.append(row)
    return pd.DataFrame(rows)


def _get_row_indices(leads: list, payload: dict) -> list:
    output_col = payload.get("output_col")
    filter_empty = payload.get("filter_empty", False)
    if filter_empty and output_col:
        return [
            i for i, lead in enumerate(leads)
            if not (lead.get("enrichment_data") or {}).get(output_col)
        ]
    return list(range(len(leads)))


def _drain_queue(pq: queue.Queue) -> None:
    try:
        while True:
            pq.get_nowait()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def process_task(task: dict) -> None:
    from core.db import get_workspace_leads
    from core.tasks import complete_task, fail_task, update_task_progress

    task_id = task["id"]
    workspace_id = task["workspace_id"]
    payload = task["payload"]
    enrichment_type = payload.get("enrichment_type", "llm")

    log.info(f"Task {task_id} started | type={enrichment_type} workspace={workspace_id}")

    if enrichment_type == "plusvibe_push":
        update_task_progress(task_id, 0)
        _run_plusvibe_push(task_id, payload)
        return

    leads = get_workspace_leads(workspace_id)
    if not leads:
        log.warning(f"Task {task_id}: no leads in workspace {workspace_id}")
        complete_task(task_id)
        return

    output_col = payload.get("output_col")
    filter_empty = payload.get("filter_empty", False)
    if filter_empty and output_col:
        leads = [l for l in leads if not (l.get("enrichment_data") or {}).get(output_col)]

    update_task_progress(task_id, 0)

    if enrichment_type == "mx":
        _run_mx(task_id, workspace_id, leads, payload)
    elif enrichment_type == "exa":
        _run_exa(task_id, workspace_id, leads, payload)
    else:
        _run_llm(task_id, workspace_id, leads, payload)


def main() -> None:
    log.info("Worker started. Waiting for tasks...")
    try:
        from core.tasks import reset_stale_tasks
        reset = reset_stale_tasks(older_than_minutes=30)
        if reset:
            log.info(f"Startup recovery: reset {reset} stale 'processing' task(s) back to 'pending'")
    except Exception as e:
        log.warning(f"Startup recovery failed (non-critical): {e}")
    while True:
        try:
            from core.tasks import claim_task, fail_task
            task = claim_task()
            if not task:
                time.sleep(2)
                continue
            log.info(f"Claimed task {task['id']}")
            try:
                process_task(task)
            except Exception as e:
                log.error(f"Task {task['id']} failed: {e}", exc_info=True)
                fail_task(task["id"], str(e))
        except Exception as e:
            log.error(f"Worker loop error: {e}", exc_info=True)
            time.sleep(5)


if __name__ == "__main__":
    main()

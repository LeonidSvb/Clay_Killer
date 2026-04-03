"""
core/tasks.py — Task management for enrichment worker.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None


def create_task(workspace_id: int, payload: dict, total: int = 0) -> Optional[int]:
    from core.db import get_connection
    conn = get_connection()
    if not conn:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tasks (workspace_id, payload, total)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (workspace_id, psycopg2.extras.Json(payload), total)
                )
                return cur.fetchone()[0]
    finally:
        conn.close()


def claim_task() -> Optional[dict]:
    """Atomically claim one pending task. Safe for multiple workers."""
    from core.db import get_connection
    conn = get_connection()
    if not conn:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE tasks
                    SET status = 'processing', started_at = NOW()
                    WHERE id = (
                        SELECT id FROM tasks
                        WHERE status = 'pending'
                        ORDER BY id
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING *
                    """
                )
                row = cur.fetchone()
                return dict(row) if row else None
    finally:
        conn.close()


def update_task_progress(task_id: int, processed: int, errors: int = 0) -> None:
    from core.db import get_connection
    conn = get_connection()
    if not conn:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE tasks SET processed = %s, errors = %s WHERE id = %s",
                    (processed, errors, task_id)
                )
    finally:
        conn.close()


def complete_task(task_id: int) -> None:
    from core.db import get_connection
    conn = get_connection()
    if not conn:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE tasks SET status = 'done', finished_at = NOW() WHERE id = %s",
                    (task_id,)
                )
    finally:
        conn.close()


def fail_task(task_id: int, error_msg: str = "") -> None:
    from core.db import get_connection
    conn = get_connection()
    if not conn:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed', finished_at = NOW(), error_msg = %s
                    WHERE id = %s
                    """,
                    (error_msg[:500], task_id)
                )
    finally:
        conn.close()


def get_workspace_tasks(workspace_id: int) -> list:
    from core.db import get_connection
    conn = get_connection()
    if not conn:
        return []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, type, status, payload, total, processed, errors,
                       error_msg, created_at, started_at, finished_at
                FROM tasks
                WHERE workspace_id = %s
                ORDER BY id DESC
                LIMIT 50
                """,
                (workspace_id,)
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_active_tasks() -> list:
    """All pending or processing tasks across all workspaces."""
    from core.db import get_connection
    conn = get_connection()
    if not conn:
        return []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT t.id, t.type, t.status, t.payload, t.total, t.processed,
                       t.errors, t.created_at, t.started_at, w.name as workspace_name
                FROM tasks t
                JOIN workspaces w ON t.workspace_id = w.id
                WHERE t.status IN ('pending', 'processing')
                ORDER BY t.id
                """
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

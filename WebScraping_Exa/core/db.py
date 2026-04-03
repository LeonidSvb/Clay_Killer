"""
core/db.py — PostgreSQL connection and helper functions.

Connects to the outreach database on the VPS.
All enrichment tables (leads_master, workspaces, workspace_leads) live there.

Usage:
    from core.db import get_connection, is_connected

    conn = get_connection()   # returns None if DATABASE_URL not set or unreachable
    if conn:
        ...
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import psycopg2
    import psycopg2.extras
    _psycopg2_available = True
except ImportError:
    _psycopg2_available = False


def get_connection():
    """
    Return a psycopg2 connection or None if DB is unavailable.
    Caller is responsible for closing the connection.
    """
    if not _psycopg2_available:
        return None
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return None
    try:
        conn = psycopg2.connect(url, options="-c search_path=enrichment,public")
        return conn
    except Exception as e:
        logger.warning("DB connection failed: %s", e)
        return None


def is_connected() -> bool:
    conn = get_connection()
    if conn:
        conn.close()
        return True
    return False


def get_workspaces() -> list[dict]:
    """Return all workspaces ordered by newest first."""
    conn = get_connection()
    if not conn:
        return []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, file_name, source, total_rows, notes, created_at
                FROM workspaces
                ORDER BY created_at DESC
            """)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_leads_master_count() -> int:
    """Return total unique leads in leads_master."""
    conn = get_connection()
    if not conn:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM leads_master")
            return cur.fetchone()[0]
    finally:
        conn.close()


def workspace_exists(file_name: str) -> Optional[dict]:
    """Return existing workspace row if same file_name was already imported, else None."""
    conn = get_connection()
    if not conn:
        return None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name, created_at FROM workspaces WHERE file_name = %s LIMIT 1",
                (file_name,)
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def import_csv_to_db(
    rows: list[dict],
    workspace_name: str,
    file_name: str,
) -> dict:
    """
    Import a list of Apollo CSV rows into leads_master + workspace_leads.

    rows: list of dicts with Apollo column names (as-is from pandas)
    Returns: {"workspace_id": int, "added": int, "existing": int, "errors": int}
    """
    conn = get_connection()
    if not conn:
        raise RuntimeError("No DB connection")

    # Apollo column → leads_master field mapping
    FIELD_MAP = {
        "Email":                       "email",
        "First Name":                  "first_name",
        "Last Name":                   "last_name",
        "Company Name":                "company_name",
        "Company Website":             "company_website",
        "Company Linkedin":            "company_linkedin",
        "LinkedIn":                    "linkedin_url",
        "Headline":                    "title",
        "City":                        "city",
        "Country":                     "country",
        "Employees Count":             "employees_count",
        "Industry":                    "industry",
        "Keywords":                    "keywords",
        "Company Annual Revenue Clean":"company_revenue",
        "Company Short Description":   "company_short_description",
    }

    added = 0
    existing = 0
    errors = 0

    try:
        with conn:
            with conn.cursor() as cur:
                # Create workspace
                cur.execute(
                    """
                    INSERT INTO workspaces (name, file_name, source, total_rows)
                    VALUES (%s, %s, 'apollo', %s)
                    RETURNING id
                    """,
                    (workspace_name, file_name, len(rows))
                )
                workspace_id = cur.fetchone()[0]

                for row in rows:
                    email = str(row.get("Email", "")).strip().lstrip("'")
                    if not email or "@" not in email:
                        errors += 1
                        continue

                    # Build leads_master fields
                    fields = {"email": email}
                    for csv_col, db_col in FIELD_MAP.items():
                        if csv_col == "Email":
                            continue
                        val = row.get(csv_col)
                        if val is not None and str(val).strip():
                            if db_col == "employees_count":
                                try:
                                    fields[db_col] = int(float(str(val).strip()))
                                except (ValueError, TypeError):
                                    pass
                            else:
                                fields[db_col] = str(val).strip()

                    cols = list(fields.keys())
                    placeholders = ["%s"] * len(cols)
                    update_cols = [c for c in cols if c != "email"]

                    if update_cols:
                        update_clause = ", ".join(
                            f"{c} = EXCLUDED.{c}" for c in update_cols
                        ) + ", updated_at = NOW()"
                    else:
                        update_clause = "updated_at = NOW()"

                    try:
                        cur.execute(
                            f"""
                            INSERT INTO leads_master ({', '.join(cols)})
                            VALUES ({', '.join(placeholders)})
                            ON CONFLICT (email) DO UPDATE SET {update_clause}
                            """,
                            [fields[c] for c in cols]
                        )

                        result = cur.execute(
                            """
                            INSERT INTO workspace_leads (workspace_id, email)
                            VALUES (%s, %s)
                            ON CONFLICT (workspace_id, email) DO NOTHING
                            """,
                            (workspace_id, email)
                        )
                        if cur.rowcount == 1:
                            added += 1
                        else:
                            existing += 1

                    except Exception as e:
                        logger.warning("Row error email=%s: %s", email, e)
                        errors += 1

        return {"workspace_id": workspace_id, "added": added, "existing": existing, "errors": errors}

    finally:
        conn.close()


def rename_workspace(workspace_id: int, new_name: str) -> bool:
    """Rename a workspace."""
    conn = get_connection()
    if not conn:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE workspaces SET name = %s WHERE id = %s",
                    (new_name, workspace_id)
                )
                return cur.rowcount == 1
    finally:
        conn.close()


def delete_workspace(workspace_id: int) -> bool:
    """Delete a workspace and its workspace_leads (cascade). Does NOT touch leads_master."""
    conn = get_connection()
    if not conn:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM workspaces WHERE id = %s", (workspace_id,))
                return cur.rowcount == 1
    finally:
        conn.close()


def save_enrichment_batch(workspace_id: int, rows: list) -> None:
    """
    Merge enrichment results into workspace_leads.data JSONB.
    rows: [{"email": str, "data": {key: value, ...}}, ...]
    """
    conn = get_connection()
    if not conn:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                for row in rows:
                    cur.execute(
                        """
                        UPDATE workspace_leads
                        SET data = data || %s::jsonb
                        WHERE workspace_id = %s AND email = %s
                        """,
                        (psycopg2.extras.Json(row["data"]), workspace_id, row["email"])
                    )
    finally:
        conn.close()


def get_plusvibe_campaigns() -> list[dict]:
    """Return active/paused/completed campaigns from public.campaigns."""
    conn = get_connection()
    if not conn:
        return []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT c.id, c.name, c.status, c.lead_count, c.replied_count, c.open_rate, c.replied_rate
                FROM public.campaigns c
                WHERE c.deleted_from_source_at IS NULL
                  AND EXISTS (
                      SELECT 1 FROM public.leads l
                      WHERE l.campaign_id = c.id
                        AND l.deleted_from_source_at IS NULL
                  )
                ORDER BY c.modified_at DESC NULLS LAST
            """)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_plusvibe_lead_statuses(campaign_id: str) -> list[str]:
    """Return distinct lead statuses present in the given campaign."""
    conn = get_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT status FROM public.leads
                WHERE campaign_id = %s
                  AND deleted_from_source_at IS NULL
                  AND status IS NOT NULL
                ORDER BY status
            """, (campaign_id,))
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def get_plusvibe_leads(campaign_id: str, statuses: list[str]) -> list[dict]:
    """Return leads for a campaign filtered by statuses.
    PlusVibe fields take priority; enrichment.leads_master fills in extra columns."""
    conn = get_connection()
    if not conn:
        return []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    l.email, l.first_name, l.last_name, l.job_title,
                    l.company_name, l.company_website, l.linkedin_person_url,
                    l.phone_number, l.city, l.country, l.mx,
                    l.status, l.label, l.sent_step, l.total_steps,
                    l.replied_count, l.opened_count, l.notes, l.enrichment,
                    lm.company_linkedin,
                    lm.linkedin_url       AS linkedin_url_apollo,
                    lm.employees_count,
                    lm.industry,
                    lm.keywords,
                    lm.company_revenue,
                    lm.company_short_description
                FROM public.leads l
                LEFT JOIN enrichment.leads_master lm ON lm.email = l.email
                WHERE l.campaign_id = %s
                  AND l.deleted_from_source_at IS NULL
                  AND l.status = ANY(%s)
                ORDER BY l.email
            """, (campaign_id, statuses))
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_workspace_leads(workspace_id: int) -> list[dict]:
    """Return all leads for a workspace with leads_master fields + workspace data jsonb."""
    conn = get_connection()
    if not conn:
        return []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    lm.email, lm.first_name, lm.last_name, lm.company_name,
                    lm.company_website, lm.title, lm.country, lm.city,
                    lm.employees_count, lm.industry,
                    wl.data as enrichment_data,
                    wl.id as wl_id
                FROM workspace_leads wl
                JOIN leads_master lm ON wl.email = lm.email
                WHERE wl.workspace_id = %s
                ORDER BY wl.id
                """,
                (workspace_id,)
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

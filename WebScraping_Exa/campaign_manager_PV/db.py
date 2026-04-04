import os
import psycopg2
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def _conn():
    return psycopg2.connect(os.getenv("DATABASE_URL"))


def get_campaigns() -> pd.DataFrame:
    sql = """
        SELECT
            id, name, status, campaign_type, parent_camp_id,
            lead_count, sent_count, lead_contacted_count, completed_lead_count,
            replied_count, bounced_count, open_rate, replied_rate,
            schedule_timezone, schedule_from_time, schedule_to_time,
            daily_limit, sequence_steps,
            last_lead_sent, created_at
        FROM public.campaigns
        WHERE status IN ('ACTIVE', 'PAUSED')
          AND deleted_from_source_at IS NULL
        ORDER BY status DESC, name
    """
    with _conn() as conn:
        return pd.read_sql(sql, conn)


def get_email_accounts() -> pd.DataFrame:
    sql = """
        SELECT id, email, domain, provider, status, warmup_status,
               daily_limit, email_sent_today, sending_gap_min
        FROM public.email_accounts
        WHERE deleted_from_source_at IS NULL
        ORDER BY domain, email
    """
    with _conn() as conn:
        return pd.read_sql(sql, conn)


def get_recent_campaign_accounts() -> pd.DataFrame:
    """Fallback: derive campaign→account mapping from emails sent in last 7 days."""
    sql = """
        SELECT DISTINCT campaign_id, sending_account AS account_email
        FROM public.emails
        WHERE sent_at > NOW() - INTERVAL '7 days'
          AND sending_account IS NOT NULL
          AND campaign_id IS NOT NULL
    """
    with _conn() as conn:
        return pd.read_sql(sql, conn)

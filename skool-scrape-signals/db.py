import os
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', 'upwork-pipeline', '.env'))

DATABASE_URL = os.environ.get('DATABASE_URL', '')


def _pg_connect():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


def get_existing_post_ids():
    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute("SELECT post_id FROM skool_signals")
    ids = {row[0] for row in cur.fetchall()}
    cur.close()
    conn.close()
    return ids


def save_signals(signals):
    if not signals:
        return 0
    conn = _pg_connect()
    cur = conn.cursor()
    saved = 0
    for s in signals:
        try:
            cur.execute("""
                INSERT INTO skool_signals
                  (post_id, post_url, post_title, category, created_at,
                   is_signal, confidence, signal_type, signal_text, reason, contact)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (post_id) DO NOTHING
            """, (
                s['post_id'],
                s.get('post_url'),
                s.get('post_title'),
                s.get('category'),
                s.get('created_at'),
                s.get('is_signal'),
                s.get('confidence'),
                s.get('signal_type'),
                s.get('signal_text'),
                s.get('reason'),
                json.dumps(s.get('contact')) if s.get('contact') else None,
            ))
            saved += cur.rowcount
        except Exception as e:
            print(f"  [db] error saving {s.get('post_id')}: {e}")
    conn.commit()
    cur.close()
    conn.close()
    return saved


def mark_notified(post_ids):
    if not post_ids:
        return
    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE skool_signals SET notified = TRUE WHERE post_id = ANY(%s)",
        (list(post_ids),)
    )
    conn.commit()
    cur.close()
    conn.close()


def get_unnotified_signals():
    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT post_id, post_url, post_title, category, confidence,
               signal_type, signal_text, contact, reason
        FROM skool_signals
        WHERE is_signal = TRUE
          AND confidence IN ('high', 'medium')
          AND notified = FALSE
        ORDER BY created_at DESC
    """)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

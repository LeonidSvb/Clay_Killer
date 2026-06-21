import json
import os
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ─── Simple TTL cache ─────────────────────────────────────────────────────────
_cache: dict = {}

def get_cached(key: str, ttl: int):
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry["ts"]) < ttl:
        return entry["data"]
    return None

def set_cached(key: str, data):
    _cache[key] = {"data": data, "ts": time.monotonic()}

# ─── Helpers ──────────────────────────────────────────────────────────────────
def _parse_status(state: str, status: str) -> str:
    s = state.lower()
    if s == "running":
        return "warning" if "unhealthy" in status.lower() else "healthy"
    if s in ("restarting", "paused"):
        return "warning"
    return "inactive"

def _parse_uptime(status: str) -> Optional[str]:
    if status.startswith("Up "):
        return status[3:].split(" (")[0].strip()
    return None

def _freshness(ts: Optional[datetime]) -> str:
    if ts is None:
        return "unknown"
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = (now - ts).total_seconds()
    if age < 3_600:
        return "fresh"
    if age < 7 * 86_400:
        return "stale"
    return "dead"

def _time_ago(ts: Optional[datetime]) -> Optional[str]:
    if ts is None:
        return None
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    secs = (now - ts).total_seconds()
    if secs < 60:
        return f"{int(secs)}s ago"
    if secs < 3_600:
        return f"{int(secs / 60)}m ago"
    if secs < 86_400:
        return f"{int(secs / 3_600)}h ago"
    return f"{int(secs / 86_400)}d ago"

def _fmt_rows(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n:,}"
    return str(n)

# ─── /api/containers ──────────────────────────────────────────────────────────
@app.get("/api/containers")
async def get_containers():
    cached = get_cached("containers", ttl=15)
    if cached is not None:
        return cached

    ps = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{json .}}"],
        capture_output=True, text=True,
    )
    raw = [json.loads(l) for l in ps.stdout.strip().splitlines() if l]

    stats_proc = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
        capture_output=True, text=True,
    )
    stats_map: dict = {}
    for l in stats_proc.stdout.strip().splitlines():
        if l:
            s = json.loads(l)
            stats_map[s.get("Name", "")] = s

    result = []
    for c in raw:
        name = c.get("Names", "").lstrip("/")
        st = stats_map.get(name, {})
        mem_raw = st.get("MemUsage", "")
        result.append({
            "id": c.get("ID", "")[:12],
            "name": name,
            "image": c.get("Image", ""),
            "status": _parse_status(c.get("State", ""), c.get("Status", "")),
            "uptime": _parse_uptime(c.get("Status", "")),
            "ram": mem_raw.split("/")[0].strip() if mem_raw else None,
            "cpu": st.get("CPUPerc") or None,
        })

    set_cached("containers", result)
    return result

# ─── /api/databases ───────────────────────────────────────────────────────────
TABLE_STATS_SQL = """
    SELECT
        relname   AS tablename,
        n_live_tup AS row_count,
        GREATEST(last_autoanalyze, last_autovacuum, last_analyze, last_vacuum) AS last_active
    FROM pg_stat_user_tables
    ORDER BY relname
"""

async def _fetch_tables(host: str, port: int, user: str, password: str, dbname: str) -> list:
    try:
        conn = await asyncpg.connect(
            host=host, port=port, user=user, password=password,
            database=dbname, timeout=5,
        )
        try:
            rows = await conn.fetch(TABLE_STATS_SQL)
            return [{
                "name": r["tablename"],
                "rows": _fmt_rows(r["row_count"]) if r["row_count"] else None,
                "lastWrite": _time_ago(r["last_active"]),
                "freshness": _freshness(r["last_active"]),
            } for r in rows]
        finally:
            await conn.close()
    except Exception:
        return []

@app.get("/api/databases")
async def get_databases():
    cached = get_cached("databases", ttl=60)
    if cached is not None:
        return cached

    sh_host = os.environ.get("SHARED_PG_HOST", "host.docker.internal")
    sh_port = int(os.environ.get("SHARED_PG_PORT", "5432"))
    sh_user = os.environ.get("SHARED_PG_USER", "app_admin")
    sh_pass = os.environ.get("SHARED_PG_PASSWORD", "")

    su_host = os.environ.get("SUPA_PG_HOST", "host.docker.internal")
    su_port = int(os.environ.get("SUPA_PG_PORT", "5434"))
    su_user = os.environ.get("SUPA_PG_USER", "postgres")
    su_pass = os.environ.get("SUPA_PG_PASSWORD", "")
    su_db   = os.environ.get("SUPA_PG_DB", "postgres")

    results = []

    for dbname in ["icegen", "outreach_sync", "platform", "tg_monitoring"]:
        tables = await _fetch_tables(sh_host, sh_port, sh_user, sh_pass, dbname)
        results.append({
            "id": f"shared-{dbname}",
            "name": f"shared-postgres / {dbname}",
            "instance": "shared-postgres",
            "host": "shared-postgres:5432",
            "status": "orphaned" if dbname == "tg_monitoring" and not tables else ("healthy" if tables else "warning"),
            "tables": tables,
            "usedBy": [],
        })

    for schema in ["public", "outreach", "enrichment"]:
        try:
            conn = await asyncpg.connect(
                host=su_host, port=su_port, user=su_user, password=su_pass,
                database=su_db, timeout=5,
            )
            try:
                rows = await conn.fetch(
                    TABLE_STATS_SQL.replace(
                        "FROM pg_stat_user_tables",
                        f"FROM pg_stat_user_tables WHERE schemaname = '{schema}'"
                    )
                )
                tables = [{
                    "name": r["tablename"],
                    "rows": _fmt_rows(r["row_count"]) if r["row_count"] else None,
                    "lastWrite": _time_ago(r["last_active"]),
                    "freshness": _freshness(r["last_active"]),
                } for r in rows]
            finally:
                await conn.close()
        except Exception:
            tables = []

        results.append({
            "id": f"supa-{schema}",
            "name": f"supabase / {schema}",
            "instance": "supabase-db",
            "schema": schema,
            "host": "supabase-db:5432",
            "status": "healthy" if tables else "warning",
            "tables": tables,
            "usedBy": [],
        })

    results.append({
        "id": "n8n-db",
        "name": "n8n-postgres / n8n",
        "instance": "n8n-postgres",
        "host": "n8n-postgres:5432",
        "status": "healthy",
        "tables": [{"name": "internal (workflows, credentials, executions)", "freshness": "unknown"}],
        "usedBy": ["n8n"],
    })

    set_cached("databases", results)
    return results

# ─── /api/status ──────────────────────────────────────────────────────────────
@app.get("/api/status")
async def get_status():
    try:
        df = subprocess.run(["df", "-h", "/"], capture_output=True, text=True)
        df_line = df.stdout.strip().splitlines()[-1].split()
        disk_used, disk_total = df_line[2], df_line[1]
        disk_pct = int(df_line[4].rstrip("%"))
    except Exception:
        disk_used = disk_total = "?"
        disk_pct = 0

    ram_str, ram_pct = "? / ?", 0
    try:
        free = subprocess.run(["free", "-m"], capture_output=True, text=True)
        mem = [l for l in free.stdout.splitlines() if l.startswith("Mem:")][0].split()
        total_mb, used_mb = int(mem[1]), int(mem[2])
        ram_str = f"{used_mb / 1024:.1f} / {total_mb / 1024:.0f} GB"
        ram_pct = round(used_mb * 100 / total_mb)
    except Exception:
        pass

    cpu_str = "?"
    try:
        stat1 = open("/proc/stat").readline().split()
        time.sleep(0.2)
        stat2 = open("/proc/stat").readline().split()
        idle1, total1 = int(stat1[4]), sum(int(x) for x in stat1[1:])
        idle2, total2 = int(stat2[4]), sum(int(x) for x in stat2[1:])
        cpu_str = f"{round((1 - (idle2 - idle1) / (total2 - total1)) * 100)}%"
    except Exception:
        pass

    try:
        uptime_raw = subprocess.run(["uptime", "-p"], capture_output=True, text=True)
        uptime_str = uptime_raw.stdout.strip().removeprefix("up ")
    except Exception:
        uptime_str = "?"

    return {
        "host": "netcup-primary",
        "ip": "152.53.194.162",
        "location": "Manassas US · ARM64 8GB",
        "cpu": cpu_str,
        "ram": ram_str,
        "ramPct": ram_pct,
        "disk": f"{disk_used} / {disk_total}",
        "diskPct": disk_pct,
        "uptime": uptime_str,
    }

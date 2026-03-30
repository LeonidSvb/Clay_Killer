"""
Lead Processing Tools — Streamlit UI
Tabs: Icebreaker Generator | MX Provider Check
Run: streamlit run streamlit_app.py
"""

import asyncio
import json
import queue
import threading
import time
from pathlib import Path

import httpx
import pandas as pd
import streamlit as st

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Lead Processing",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── MX Provider constants ──────────────────────────────────────────────────────
MX_DIRECT = [
    ("Google",      ["aspmx.l.google.com", "googlemail.com", "alt1.aspmx", "alt2.aspmx",
                     "aspmx2.googlemail", "aspmx3.googlemail"]),
    ("Microsoft",   ["mail.protection.outlook.com", "olc.protection.outlook.com", "outlook.com"]),
    ("Mimecast",    ["mimecast.com"]),
    ("Proofpoint",  ["pphosted.com"]),
    ("Barracuda",   ["barracudanetworks.com"]),
    ("Zoho",        ["zoho.com", "zoho.eu"]),
    ("ProtonMail",  ["protonmail.ch"]),
    ("Yahoo",       ["yahoodns.net"]),
]

MX_GATEWAYS = {
    "hornetsecurity.com":   "Hornetsecurity",
    "ppe-hosted.com":       "Proofpoint Essentials",
    "sophos.com":           "Sophos",
    "trendmicro.com":       "Trend Micro",
    "zerospam.ca":          "ZeroSpam",
    "antispameurope.com":   "Antispam Europe",
    "mtaroutes.com":        "MTA Routes",
    "mxthunder.net":        "MX Thunder",
    "mxthunder.com":        "MX Thunder",
    "iphmx.com":            "Cisco IronPort",
    "arsmtp.com":           "AR SMTP",
    "emailservice.co":      "Email Service",
    "emailservice.io":      "Email Service",
    "emailservice.cc":      "Email Service",
    "siteprotect.com":      "SiteProtect",
    "mailhop.org":          "Mailhop",
    "titanhq.com":          "TitanHQ",
    "gosecure.net":         "GoSecure",
    "esvacloud.com":        "ESVA Cloud",
    "megamailservers.com":  "Mega Mail Servers",
    "mycloudmailbox.com":   "My Cloud Mailbox",
    "ncisystems.com":       "NCI Systems",
}

SPF_MS     = ["spf.protection.outlook.com", "onmicrosoft.com", "sharepointonline.com"]
SPF_GOOGLE = ["_spf.google.com", "googlemail.com"]


def mx_classify(mx_list: list, txt: str) -> tuple:
    if not mx_list:
        return "No MX", ""
    combined = " ".join(mx_list).lower()
    for name, patterns in MX_DIRECT:
        if any(p in combined for p in patterns):
            return name, ""
    parts = mx_list[0].rstrip(".").split(".")
    root = ".".join(parts[-2:]) if len(parts) >= 2 else mx_list[0]
    gname = MX_GATEWAYS.get(root, root)
    hint = ("Microsoft" if any(p in txt for p in SPF_MS)
            else "Google" if any(p in txt for p in SPF_GOOGLE) else "")
    return "Other", f"{gname} ({hint})" if hint else gname


def mx_get_domain(email: str) -> str:
    email = (email or "").strip().lower()
    return email.split("@", 1)[1] if "@" in email else ""


async def _mx_fetch(client: httpx.AsyncClient, sem: asyncio.Semaphore, domain: str):
    async with sem:
        mx, txt = [], ""
        for rtype in ("MX", "TXT"):
            for attempt in range(3):
                try:
                    url = f"https://dns.google/resolve?name={domain}&type={rtype}"
                    r = await client.get(url, timeout=8.0)
                    if r.status_code == 429:
                        await asyncio.sleep(attempt + 1)
                        continue
                    data = r.json()
                    ans = data.get("Answer", [])
                    if rtype == "MX":
                        mx = [
                            a["data"].split(" ", 1)[-1].rstrip(".").lower()
                            for a in ans if a.get("type") == 15
                        ]
                    else:
                        txt = " ".join(a["data"] for a in ans if a.get("type") == 16).lower()
                    break
                except Exception:
                    await asyncio.sleep(0.3)
        provider, gateway = mx_classify(mx, txt)
        return domain, provider, gateway


async def _mx_batch(domains: list, rq: queue.Queue, stop_event: threading.Event, concurrency: int):
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient() as client:
        tasks = [asyncio.create_task(_mx_fetch(client, sem, d)) for d in domains]
        for coro in asyncio.as_completed(tasks):
            if stop_event.is_set():
                for t in tasks:
                    t.cancel()
                break
            try:
                result = await coro
                rq.put(result)
            except Exception:
                pass


def _mx_thread_runner(domains: list, rq: queue.Queue, stop_event: threading.Event, concurrency: int):
    asyncio.run(_mx_batch(domains, rq, stop_event, concurrency))
    rq.put(None)

CONFIG_PATH = Path(__file__).parent / "icebreaker_config.json"

DEFAULTS = {
    "openrouter_api_key": "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",
    "model": "openai/gpt-oss-120b",
    "concurrency": 50,
    "limit": 50,
    "provider_sort": "throughput",
    "max_tokens": 500,
    "temperature": 0.8,
    "spreadsheet_id": "1GDYmXYkGf6FTwFrm35bIyJGr1tcl4G_qv5KhTQoe5Qg",
    "sheet_name": "Sheet20",
    "input_col_1": "Website Summary",
    "input_col_2": "Company Short Description",
    "output_col": "Personalisation",
    "service_account_path": "",
    "apps_script_url": "",
    "data_mode": "csv",
    "prompt": (
        "You are writing a cold outreach opener for a recruitment company.\n"
        " \n"
        "Based on the company summary below, write exactly the line:\n"
        " \n"
        "Figured I'd reach out - I'm around [dreamICP] daily and they keep saying they [painTheySolve].\n"
        " \n"
        "Rules:\n"
        "- [dreamICP] must be a plural ICP group in casual operator language "
        "(e.g. \"founders running SaaS teams\", \"ops directors at logistics firms\") "
        "-- NO corporate terms like \"decision-makers\" or \"stakeholders\"\n"
        "- [painTheySolve] must be a hiring-related complaint in founder casual tone "
        "(e.g. \"been searching for months and keep seeing the same 10 CVs\", "
        "\"can't close a senior role without it dragging on forever\") "
        "-- infer from the company's ICP and industry even if not stated explicitly\n"
        "- Tone must sound like a founder texting another founder -- casual, insider, not corporate\n"
        "- Use shorthand like: \"burning weeks on\", \"pipeline's dry\", "
        "\"nobody shows up qualified\", \"keeps falling through\"\n"
        "- NOT like: \"struggle to find qualified talent\", \"face challenges in recruitment\"\n"
        "- Output ONLY the 1 line, nothing else\n"
        " \n"
        "Company info:"
    ),
}


# ── Config ─────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        return {**DEFAULTS, **saved}
    return dict(DEFAULTS)


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ── Session state ──────────────────────────────────────────────────────────────
if "cfg" not in st.session_state:
    st.session_state.cfg = load_config()
if "run_state" not in st.session_state:
    st.session_state.run_state = "idle"
if "results" not in st.session_state:
    st.session_state.results = []
if "stop_event" not in st.session_state:
    st.session_state.stop_event = threading.Event()
if "result_queue" not in st.session_state:
    st.session_state.result_queue = queue.Queue()
if "stats" not in st.session_state:
    st.session_state.stats = {}
if "loaded_df" not in st.session_state:
    st.session_state.loaded_df = None

# MX session state
if "mx_run_state" not in st.session_state:
    st.session_state.mx_run_state = "idle"
if "mx_df" not in st.session_state:
    st.session_state.mx_df = None
if "mx_domain_results" not in st.session_state:
    st.session_state.mx_domain_results = {}
if "mx_stop_event" not in st.session_state:
    st.session_state.mx_stop_event = threading.Event()
if "mx_result_queue" not in st.session_state:
    st.session_state.mx_result_queue = queue.Queue()
if "mx_stats" not in st.session_state:
    st.session_state.mx_stats = {}

cfg = st.session_state.cfg


# ── Google Sheets helpers ──────────────────────────────────────────────────────
def get_gc():
    sa_path = cfg.get("service_account_path", "").strip()
    if not sa_path or not Path(sa_path).exists():
        return None
    try:
        import gspread
        return gspread.service_account(filename=sa_path)
    except Exception as e:
        st.error(f"Google Sheets auth: {e}")
        return None


def sheets_load_pending() -> pd.DataFrame | None:
    gc = get_gc()
    if not gc:
        return None
    try:
        ws = gc.open_by_key(cfg["spreadsheet_id"]).worksheet(cfg["sheet_name"])
        rows = ws.get_all_records()
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["row_number"] = range(2, len(df) + 2)
        out = cfg["output_col"]
        if out in df.columns:
            df = df[df[out].astype(str).str.strip() == ""]
        return df
    except Exception as e:
        st.error(f"Sheet load error: {e}")
        return None


def sheets_write(results: list[dict]) -> int:
    import gspread
    gc = get_gc()
    if not gc:
        return 0
    ws = gc.open_by_key(cfg["spreadsheet_id"]).worksheet(cfg["sheet_name"])
    headers = ws.row_values(1)
    out_col = cfg["output_col"]
    if out_col not in headers:
        st.error(f"Column '{out_col}' not found in sheet.")
        return 0
    col_idx = headers.index(out_col) + 1
    updates = [
        {"range": gspread.utils.rowcol_to_a1(r["row_number"], col_idx), "values": [[r["content"]]]}
        for r in results if r.get("ok") and r.get("content")
    ]
    if updates:
        ws.batch_update(updates)
    return len(updates)


# ── Apps Script helpers ────────────────────────────────────────────────────────
def appsscript_load_pending() -> pd.DataFrame | None:
    url = cfg.get("apps_script_url", "").strip()
    if not url:
        st.error("Apps Script URL not set in sidebar.")
        return None
    try:
        params = {
            "sheet": cfg["sheet_name"],
            "output_col": cfg["output_col"],
        }
        if cfg["limit"] > 0:
            params["limit"] = str(cfg["limit"])

        r = httpx.get(url, params=params, timeout=30.0, follow_redirects=True)
        data = r.json()
        if data.get("status") != "ok":
            st.error(f"Apps Script error: {data.get('message')}")
            return None
        rows = data.get("rows", [])
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)
    except Exception as e:
        st.error(f"Apps Script fetch error: {e}")
        return None


def appsscript_write(results: list[dict]) -> int:
    url = cfg.get("apps_script_url", "").strip()
    if not url:
        return 0
    updates = [
        {"row_number": r["row_number"], "value": r["content"]}
        for r in results if r.get("ok") and r.get("content")
    ]
    if not updates:
        return 0
    try:
        payload = {
            "sheet": cfg["sheet_name"],
            "output_col": cfg["output_col"],
            "updates": updates,
        }
        r = httpx.post(url, json=payload, timeout=60.0, follow_redirects=True)
        data = r.json()
        if data.get("status") != "ok":
            st.error(f"Apps Script write error: {data.get('message')}")
            return 0
        return data.get("written", 0)
    except Exception as e:
        st.error(f"Apps Script write error: {e}")
        return 0


# ── Async core ─────────────────────────────────────────────────────────────────
async def _one(client, sem, item, cfg_snap, stop_event):
    if stop_event.is_set():
        return {"row_number": item.get("row_number"), "ok": False, "error": "stopped", "content": ""}

    col1 = cfg_snap["input_col_1"]
    col2 = cfg_snap["input_col_2"]
    summary = str(item.get(col1) or "").strip()
    desc = str(item.get(col2) or "").strip()
    prompt = cfg_snap["prompt"] + "\n\n" + summary + "\n\n" + desc

    async with sem:
        if stop_event.is_set():
            return {"row_number": item.get("row_number"), "ok": False, "error": "stopped", "content": ""}
        t = time.perf_counter()
        try:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={
                    "model": cfg_snap["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": cfg_snap["temperature"],
                    "max_tokens": cfg_snap["max_tokens"],
                    "provider": {"sort": cfg_snap["provider_sort"]},
                },
                timeout=90.0,
            )
            elapsed = time.perf_counter() - t
            d = r.json()
            if "choices" not in d:
                return {"row_number": item.get("row_number"), "ok": False,
                        "error": str(d)[:120], "content": "", "elapsed": elapsed, "cost": 0}
            content = (d["choices"][0]["message"]["content"] or "").strip()
            cost = (d.get("usage") or {}).get("cost") or 0
            return {"row_number": item.get("row_number"), "ok": True,
                    "content": content, "elapsed": elapsed, "cost": cost, "error": None}
        except Exception as e:
            return {"row_number": item.get("row_number"), "ok": False,
                    "error": str(e)[:120], "content": "", "elapsed": time.perf_counter() - t, "cost": 0}


async def _batch(leads, cfg_snap, rq, stop_event):
    sem = asyncio.Semaphore(cfg_snap["concurrency"])
    headers = {"Authorization": f"Bearer {cfg_snap['openrouter_api_key']}",
               "Content-Type": "application/json"}
    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [_one(client, sem, dict(row), cfg_snap, stop_event) for row in leads]
        for coro in asyncio.as_completed(tasks):
            rq.put(await coro)


def _thread_runner(leads, cfg_snap, rq, stop_event):
    asyncio.run(_batch(leads, cfg_snap, rq, stop_event))
    rq.put(None)


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### AI Config")
    cfg["openrouter_api_key"] = st.text_input("OpenRouter API Key",
                                               value=cfg["openrouter_api_key"], type="password")
    cfg["model"] = st.text_input("Model", value=cfg["model"])

    c1, c2 = st.columns(2)
    cfg["concurrency"] = c1.number_input("Concurrency", 1, 200, value=cfg["concurrency"], step=10)
    cfg["limit"] = c2.number_input("Limit (0=all)", 0, 50000, value=cfg["limit"], step=50)

    cfg["provider_sort"] = st.selectbox(
        "Provider sort",
        ["throughput", "latency", "price"],
        index=["throughput", "latency", "price"].index(cfg.get("provider_sort", "throughput")),
    )

    st.markdown("---")
    st.markdown("### Data Source")

    mode_options = ["csv", "apps_script", "google_sheets"]
    mode_labels  = ["CSV upload/download", "Google Sheets (Apps Script)", "Google Sheets (Service Account)"]
    current_mode = cfg.get("data_mode", "csv")
    mode_idx = mode_options.index(current_mode) if current_mode in mode_options else 0

    cfg["data_mode"] = st.radio(
        "Mode", mode_options,
        format_func=lambda x: mode_labels[mode_options.index(x)],
        index=mode_idx,
    )

    if cfg["data_mode"] == "apps_script":
        cfg["apps_script_url"] = st.text_input(
            "Apps Script Web App URL",
            value=cfg.get("apps_script_url", ""),
            placeholder="https://script.google.com/macros/s/.../exec",
            help="Deploy the script from google_apps_script.js, paste URL here",
        )
        cfg["sheet_name"] = st.text_input("Sheet tab", value=cfg["sheet_name"])

    elif cfg["data_mode"] == "google_sheets":
        cfg["service_account_path"] = st.text_input(
            "service_account.json path",
            value=cfg.get("service_account_path", ""),
            placeholder="C:/path/to/service_account.json",
        )
        cfg["spreadsheet_id"] = st.text_input("Spreadsheet ID", value=cfg["spreadsheet_id"])
        cfg["sheet_name"] = st.text_input("Sheet tab", value=cfg["sheet_name"])

    st.markdown("---")
    st.markdown("### Column Mapping")
    c3, c4 = st.columns(2)
    cfg["input_col_1"] = c3.text_input("Input col 1", value=cfg["input_col_1"])
    cfg["input_col_2"] = c4.text_input("Input col 2", value=cfg["input_col_2"])
    cfg["output_col"] = st.text_input("Output column", value=cfg["output_col"])

    st.markdown("---")
    st.markdown("### Prompt")
    cfg["prompt"] = st.text_area("", value=cfg["prompt"], height=320)

    if st.button("Save config", use_container_width=True):
        save_config(cfg)
        st.success("Saved to icebreaker_config.json")


# ── Main ───────────────────────────────────────────────────────────────────────
tab_ice, tab_mx = st.tabs(["Icebreaker Generator", "MX Provider Check"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Icebreaker Generator
# ══════════════════════════════════════════════════════════════════════════════
with tab_ice:
    st.markdown("## Icebreaker Generator")

    run_state = st.session_state.run_state

    # ── Data loading ──────────────────────────────────────────────────────────
    leads_df: pd.DataFrame | None = None

    if cfg["data_mode"] == "csv":
        uploaded = st.file_uploader(
            "Upload CSV with leads (must have header row)",
            type=["csv"],
            help=f"Required columns: '{cfg['input_col_1']}', '{cfg['input_col_2']}'. "
                 f"Optional: 'row_number' (if absent, auto-generated). "
                 f"Rows where '{cfg['output_col']}' is non-empty will be skipped.",
        )
        if uploaded:
            try:
                df = pd.read_csv(uploaded)
                if "row_number" not in df.columns:
                    df["row_number"] = range(2, len(df) + 2)
                out = cfg["output_col"]
                if out in df.columns:
                    before = len(df)
                    df = df[df[out].astype(str).str.strip() == ""]
                    skipped = before - len(df)
                else:
                    skipped = 0
                st.session_state.loaded_df = df
                if skipped:
                    st.caption(f"Skipped {skipped} rows that already have '{out}'")
            except Exception as e:
                st.error(f"CSV parse error: {e}")

        if st.session_state.loaded_df is not None:
            leads_df = st.session_state.loaded_df

    elif cfg["data_mode"] == "apps_script":
        col_reload, _ = st.columns([1, 3])
        if col_reload.button("Load from Google Sheets"):
            with st.spinner("Fetching pending leads..."):
                st.session_state.loaded_df = appsscript_load_pending()
        if st.session_state.loaded_df is not None:
            leads_df = st.session_state.loaded_df

    else:
        col_reload, _ = st.columns([1, 3])
        if col_reload.button("Reload from Google Sheets"):
            with st.spinner("Loading..."):
                st.session_state.loaded_df = sheets_load_pending()
        if st.session_state.loaded_df is not None:
            leads_df = st.session_state.loaded_df

    # ── Info bar ──────────────────────────────────────────────────────────────
    if leads_df is not None and not leads_df.empty:
        total_pending = len(leads_df)
        limit = cfg["limit"]
        will_process = total_pending if limit == 0 else min(limit, total_pending)
        col_info, col_dry = st.columns([4, 1])
        col_info.info(
            f"**{total_pending}** pending leads — will process **{will_process}** "
            f"(concurrency {cfg['concurrency']}, sort={cfg['provider_sort']})"
        )
        dry_run = col_dry.toggle("Dry run", value=True,
                                  help="Generate without writing results — check quality first")
    elif leads_df is not None:
        st.warning("No pending leads (all rows already have icebreakers).")
        dry_run = True
    else:
        if cfg["data_mode"] == "csv":
            st.info("Upload a CSV file above to get started.")
        dry_run = True

    # ── Run / Stop buttons ────────────────────────────────────────────────────
    col_run, col_stop = st.columns([3, 1])
    run_label = "Running..." if run_state == "running" else (
        "Generate (dry run)" if (leads_df is not None and dry_run) else "Generate + Write to Sheet"
    )
    run_clicked = col_run.button(
        run_label, type="primary",
        disabled=(run_state == "running" or leads_df is None or leads_df.empty),
        use_container_width=True,
    )
    stop_clicked = col_stop.button("Stop", disabled=(run_state != "running"), use_container_width=True)

    if stop_clicked:
        st.session_state.stop_event.set()

    # ── Kick off run ──────────────────────────────────────────────────────────
    if run_clicked and run_state != "running":
        limit = cfg["limit"]
        leads = leads_df.to_dict("records")
        if limit > 0:
            leads = leads[:limit]
        st.session_state.results = []
        st.session_state.stop_event = threading.Event()
        st.session_state.result_queue = queue.Queue()
        st.session_state.run_state = "running"
        st.session_state.stats = {
            "total": len(leads),
            "started_at": time.perf_counter(),
            "dry_run": dry_run,
        }
        cfg_snap = dict(cfg)
        threading.Thread(
            target=_thread_runner,
            args=(leads, cfg_snap, st.session_state.result_queue, st.session_state.stop_event),
            daemon=True,
        ).start()
        st.rerun()

    # ── Progress UI ───────────────────────────────────────────────────────────
    if run_state == "running":
        rq = st.session_state.result_queue
        stats = st.session_state.stats
        total = stats["total"]
        prog_bar = st.progress(0.0)
        status_ph = st.empty()
        table_ph = st.empty()

        while True:
            done = False
            while True:
                try:
                    item = rq.get_nowait()
                    if item is None:
                        done = True
                        break
                    st.session_state.results.append(item)
                except queue.Empty:
                    break

            results = st.session_state.results
            n_done = len(results)
            n_ok = sum(1 for r in results if r.get("ok"))
            n_err = n_done - n_ok
            total_cost = sum(r.get("cost") or 0 for r in results)
            elapsed = time.perf_counter() - stats["started_at"]
            speed = n_done / elapsed if elapsed > 0 else 0
            eta = (total - n_done) / speed if speed > 0 and n_done < total else 0

            prog_bar.progress(min(n_done / total, 1.0) if total else 0)

            if st.session_state.stop_event.is_set():
                status_ph.warning(f"Stopped at {n_done}/{total}")
            elif done:
                status_ph.success(f"Done — {n_ok}/{total} ok, {n_err} errors, {elapsed:.0f}s, ${total_cost:.4f}")
            else:
                eta_str = f"{int(eta // 60)}:{int(eta % 60):02d}" if eta > 0 else "--:--"
                status_ph.markdown(
                    f"**{n_done}/{total}** &nbsp;|&nbsp; "
                    f"**{speed:.1f}** leads/sec &nbsp;|&nbsp; "
                    f"ETA **{eta_str}** &nbsp;|&nbsp; "
                    f"cost **${total_cost:.4f}** &nbsp;|&nbsp; "
                    f"errors **{n_err}**"
                )

            if results:
                preview_rows = [
                    {
                        "row": r.get("row_number", ""),
                        "icebreaker": (r.get("content") or r.get("error") or "")[:110],
                        "s": f"{r.get('elapsed', 0):.1f}",
                        "": "ok" if r.get("ok") else "err",
                    }
                    for r in reversed(results[-15:])
                ]
                table_ph.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)

            if done or st.session_state.stop_event.is_set():
                st.session_state.run_state = "done"
                break

            time.sleep(0.4)

        st.rerun()

    # ── Results ───────────────────────────────────────────────────────────────
    if run_state == "done" and st.session_state.results:
        results = st.session_state.results
        stats = st.session_state.stats
        total = stats["total"]
        n_ok = sum(1 for r in results if r.get("ok"))
        n_err = len(results) - n_ok
        total_cost = sum(r.get("cost") or 0 for r in results)
        elapsed = time.perf_counter() - stats["started_at"]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Processed", f"{len(results)}/{total}")
        m2.metric("Success", f"{n_ok} ({100 * n_ok // max(len(results), 1)}%)")
        m3.metric("Time", f"{elapsed:.0f}s")
        m4.metric("Cost", f"${total_cost:.4f}")

        st.divider()

        ok_results = [r for r in results if r.get("ok")]
        df_out = pd.DataFrame([
            {"row_number": r["row_number"], cfg["output_col"]: r["content"]}
            for r in ok_results
        ])
        st.dataframe(df_out, use_container_width=True, hide_index=True, height=380)

        col_w, col_csv, col_merge, col_new = st.columns(4)

        with col_w:
            if stats.get("dry_run"):
                if cfg["data_mode"] == "apps_script":
                    if st.button("Write to Google Sheets", type="primary", use_container_width=True):
                        with st.spinner("Writing..."):
                            n = appsscript_write(ok_results)
                        st.success(f"Written {n} rows")
                elif cfg["data_mode"] == "google_sheets":
                    if st.button("Write to Google Sheets", type="primary", use_container_width=True):
                        with st.spinner("Writing..."):
                            n = sheets_write(ok_results)
                        st.success(f"Written {n} rows")
                else:
                    st.caption("(CSV mode — use Download below)")

        with col_csv:
            csv_bytes = df_out.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download results CSV",
                data=csv_bytes,
                file_name="icebreakers_results.csv",
                mime="text/csv",
                use_container_width=True,
            )

        with col_merge:
            if leads_df is not None and cfg["data_mode"] == "csv":
                merged = leads_df.copy()
                result_map = {r["row_number"]: r["content"] for r in ok_results}
                merged[cfg["output_col"]] = merged["row_number"].map(result_map).fillna("")
                merged_bytes = merged.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "Download full CSV (merged)",
                    data=merged_bytes,
                    file_name="icebreakers_merged.csv",
                    mime="text/csv",
                    use_container_width=True,
                    help="Original CSV with icebreakers filled in — ready to re-import",
                )

        with col_new:
            if st.button("New run", use_container_width=True):
                st.session_state.run_state = "idle"
                st.session_state.results = []
                st.rerun()

        if n_err > 0:
            with st.expander(f"Failed rows ({n_err})"):
                st.dataframe(
                    pd.DataFrame([
                        {"row": r["row_number"], "error": r.get("error", "")}
                        for r in results if not r.get("ok") and r.get("error") != "stopped"
                    ]),
                    use_container_width=True,
                    hide_index=True,
                )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — MX Provider Check
# ══════════════════════════════════════════════════════════════════════════════
with tab_mx:
    st.markdown("## MX Provider Check")

    mx_run_state = st.session_state.mx_run_state

    # ── Upload + settings ─────────────────────────────────────────────────────
    mx_uploaded = st.file_uploader(
        "Upload CSV (нужна колонка Email)",
        type=["csv"],
        key="mx_uploader",
    )
    if mx_uploaded:
        try:
            st.session_state.mx_df = pd.read_csv(mx_uploaded)
        except Exception as e:
            st.error(f"CSV parse error: {e}")

    mx_df = st.session_state.mx_df

    if mx_df is not None:
        col_set1, col_set2, col_set3 = st.columns([2, 1, 1])
        mx_cols = list(mx_df.columns)
        default_email_col = next((c for c in mx_cols if c.strip().lower() == "email"), mx_cols[0])
        mx_email_col = col_set1.selectbox("Колонка Email", mx_cols, index=mx_cols.index(default_email_col))
        mx_concurrency = col_set2.number_input("Concurrency", 10, 100, value=40, step=10)
        n_with_email = mx_df[mx_email_col].str.contains('@', na=False).sum()
        n_unique_domains = mx_df[mx_email_col].apply(lambda e: mx_get_domain(str(e))).nunique()
        st.info(f"**{len(mx_df)}** строк &nbsp;|&nbsp; **{n_with_email}** с email &nbsp;|&nbsp; **{n_unique_domains}** уникальных доменов")

    # ── Run / Stop ────────────────────────────────────────────────────────────
    col_mx_run, col_mx_stop = st.columns([3, 1])
    mx_run_clicked = col_mx_run.button(
        "Running..." if mx_run_state == "running" else "Check MX Providers",
        type="primary",
        disabled=(mx_run_state == "running" or mx_df is None),
        use_container_width=True,
        key="mx_run_btn",
    )
    mx_stop_clicked = col_mx_stop.button(
        "Stop",
        disabled=(mx_run_state != "running"),
        use_container_width=True,
        key="mx_stop_btn",
    )

    if mx_stop_clicked:
        st.session_state.mx_stop_event.set()

    # ── Kick off ──────────────────────────────────────────────────────────────
    if mx_run_clicked and mx_run_state != "running" and mx_df is not None:
        domains = list({
            mx_get_domain(e)
            for e in mx_df[mx_email_col].astype(str)
            if "@" in str(e)
        })
        domains = [d for d in domains if d]

        st.session_state.mx_domain_results = {}
        st.session_state.mx_stop_event = threading.Event()
        st.session_state.mx_result_queue = queue.Queue()
        st.session_state.mx_run_state = "running"
        st.session_state.mx_stats = {
            "total_domains": len(domains),
            "total_rows": len(mx_df),
            "started_at": time.perf_counter(),
            "email_col": mx_email_col,
        }

        threading.Thread(
            target=_mx_thread_runner,
            args=(domains, st.session_state.mx_result_queue,
                  st.session_state.mx_stop_event, int(mx_concurrency)),
            daemon=True,
        ).start()
        st.rerun()

    # ── Progress ──────────────────────────────────────────────────────────────
    if mx_run_state == "running":
        mx_rq = st.session_state.mx_result_queue
        mx_stats = st.session_state.mx_stats
        total_domains = mx_stats["total_domains"]

        mx_prog = st.progress(0.0)
        mx_status = st.empty()

        while True:
            done = False
            while True:
                try:
                    item = mx_rq.get_nowait()
                    if item is None:
                        done = True
                        break
                    domain, provider, gateway = item
                    st.session_state.mx_domain_results[domain] = (provider, gateway)
                except queue.Empty:
                    break

            n_done = len(st.session_state.mx_domain_results)
            elapsed = time.perf_counter() - mx_stats["started_at"]
            speed = n_done / elapsed if elapsed > 0 else 0
            eta = (total_domains - n_done) / speed if speed > 0 and n_done < total_domains else 0
            eta_str = f"{int(eta // 60)}:{int(eta % 60):02d}" if eta > 0 else "--:--"

            mx_prog.progress(min(n_done / total_domains, 1.0) if total_domains else 0)

            if st.session_state.mx_stop_event.is_set():
                mx_status.warning(f"Остановлено на {n_done}/{total_domains} доменах")
            elif done:
                mx_status.success(f"Готово — {total_domains} доменов за {elapsed:.0f}s")
            else:
                mx_status.markdown(
                    f"**{n_done}/{total_domains}** доменов &nbsp;|&nbsp; "
                    f"**{speed:.0f}** dom/sec &nbsp;|&nbsp; ETA **{eta_str}**"
                )

            if done or st.session_state.mx_stop_event.is_set():
                st.session_state.mx_run_state = "done"
                break

            time.sleep(0.3)

        st.rerun()

    # ── Results ───────────────────────────────────────────────────────────────
    if mx_run_state == "done" and st.session_state.mx_domain_results and mx_df is not None:
        mx_stats = st.session_state.mx_stats
        domain_results = st.session_state.mx_domain_results
        email_col = mx_stats.get("email_col", "Email")
        elapsed = time.perf_counter() - mx_stats["started_at"]

        # Map results to rows
        result_df = mx_df.copy()
        result_df["mx_provider"] = result_df[email_col].apply(
            lambda e: domain_results.get(mx_get_domain(str(e)), ("No email", ""))[0]
        )
        result_df["mx_gateway"] = result_df[email_col].apply(
            lambda e: domain_results.get(mx_get_domain(str(e)), ("No email", ""))[1]
        )

        # Stats
        provider_counts = result_df["mx_provider"].value_counts()
        total_rows = len(result_df)

        st.divider()
        cols_metrics = st.columns(min(len(provider_counts), 6))
        for i, (provider, count) in enumerate(provider_counts.items()):
            if i < len(cols_metrics):
                cols_metrics[i].metric(provider, count, f"{100*count//total_rows}%")

        st.divider()

        # Filter
        filter_col, _, dl_col, new_col = st.columns([2, 2, 1, 1])
        providers_list = ["All"] + list(provider_counts.index)
        selected = filter_col.selectbox("Фильтр по провайдеру", providers_list, key="mx_filter")

        display_df = result_df if selected == "All" else result_df[result_df["mx_provider"] == selected]
        st.dataframe(display_df, use_container_width=True, hide_index=True, height=420)

        with dl_col:
            csv_out = result_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "Download CSV",
                data=csv_out,
                file_name="leads_mx.csv",
                mime="text/csv",
                use_container_width=True,
            )

        with new_col:
            if st.button("New check", use_container_width=True, key="mx_new"):
                st.session_state.mx_run_state = "idle"
                st.session_state.mx_df = None
                st.session_state.mx_domain_results = {}
                st.rerun()

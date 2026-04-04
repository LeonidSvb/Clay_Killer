import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import streamlit as st
import pandas as pd
from db import get_campaigns, get_email_accounts, get_recent_campaign_accounts
from api import get_all_campaigns_full, extract_account_emails, extract_schedule_days, parse_schedule_days
from capacity import compute

st.set_page_config(page_title="Overview", layout="wide")
st.title("Overview")


@st.cache_data(ttl=300, show_spinner="Загружаем данные...")
def load():
    campaigns_db = get_campaigns()
    accounts_db  = get_email_accounts()
    acc_limit    = dict(zip(accounts_db["email"], accounts_db["daily_limit"].fillna(0)))

    camp_accounts: dict[str, list[str]] = {}
    camp_days:     dict[str, set[int]]  = {}
    api_ok = True
    try:
        for c in get_all_campaigns_full():
            cid = c.get("id") or c.get("_id") or c.get("camp_id", "")
            if not cid:
                continue
            camp_accounts[cid] = extract_account_emails(c)
            camp_days[cid]     = parse_schedule_days(extract_schedule_days(c))
    except Exception:
        api_ok = False
        try:
            for _, row in get_recent_campaign_accounts().iterrows():
                camp_accounts.setdefault(row["campaign_id"], []).append(row["account_email"])
            for cid in camp_accounts:
                camp_days[cid] = {0, 1, 2, 3, 4}
        except Exception:
            pass

    capacities, mode, total_pool = compute(campaigns_db, acc_limit, camp_accounts, camp_days)
    return capacities, mode, total_pool, len(accounts_db), api_ok


capacities, mode, total_pool, num_accounts, api_ok = load()

_, col_btn = st.columns([8, 1])
with col_btn:
    if st.button("Refresh"):
        st.cache_data.clear()
        st.rerun()

if not api_ok:
    st.warning("API недоступен — account mapping из emails таблицы (последние 7 дней).")

# Mode banner
if mode == "communism":
    st.success(f"Режим: COMMUNISM — все {num_accounts} аккаунтов шарятся между кампаниями. Cap/день делится поровну.")
else:
    st.info(f"Режим: SPLIT — аккаунты разделены между кампаниями.")

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
active = [c for c in capacities if c.status == "ACTIVE"]
total_daily = sum(c.daily_cap for c in active)
total_remaining = sum(c.remaining for c in capacities)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Всего аккаунтов", num_accounts)
c2.metric("Total pool / день", total_pool)
c3.metric("Активных кампаний", len(active))
c4.metric("Cap на кампанию / день", total_daily // len(active) if active else 0)

st.divider()

# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------
DAY_LABELS = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Вс"}

rows = []
for c in capacities:
    days_str = " ".join(DAY_LABELS[d] for d in sorted(c.schedule_days)) if c.schedule_days else "—"
    rows.append({
        "Кампания":       c.campaign_name,
        "Статус":         c.status.replace("*", ""),
        "Осталось":       c.remaining,
        "Cap/день":       c.daily_cap,
        "Дней/нед":       len(c.schedule_days),
        "Расписание":     days_str,
        "ETA (дней)":     c.eta_days if c.eta_days is not None else "—",
        "_status_raw":    c.status,
    })

df = pd.DataFrame(rows)

def highlight(row):
    n = len(df.columns)
    styles = [""] * n
    si = list(df.columns).index("Статус")
    if row["_status_raw"] == "ACTIVE":
        styles[si] = "background-color: #1a3a1a; color: #5dbb5d"
    else:
        styles[si] = "background-color: #3a2a1a; color: #cc8844"
    return styles

display_cols = ["Кампания", "Статус", "Осталось", "Cap/день", "Дней/нед", "Расписание", "ETA (дней)"]
st.dataframe(
    df[display_cols + ["_status_raw"]]
    .style.apply(highlight, axis=1)
    .hide(subset=["_status_raw"], axis="columns"),
    use_container_width=True,
    hide_index=True,
)

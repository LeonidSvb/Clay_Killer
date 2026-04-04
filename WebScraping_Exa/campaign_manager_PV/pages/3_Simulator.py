import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import math
from datetime import date, timedelta
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from db import get_campaigns, get_email_accounts, get_recent_campaign_accounts
from api import get_all_campaigns_full, extract_account_emails, extract_schedule_days, parse_schedule_days
from capacity import compute, project_sends, COMMUNISM_THRESHOLD

st.set_page_config(page_title="Simulator", layout="wide")
st.title("Simulator — What If")
st.caption("Запусти паузнутую кампанию в X дату — посмотри как изменится расписание")


@st.cache_data(ttl=300, show_spinner="Загружаем данные...")
def load():
    campaigns_db = get_campaigns()
    accounts_db  = get_email_accounts()
    acc_limit    = dict(zip(accounts_db["email"], accounts_db["daily_limit"].fillna(0)))

    camp_accounts: dict[str, list[str]] = {}
    camp_days:     dict[str, set[int]]  = {}
    try:
        for c in get_all_campaigns_full():
            cid = c.get("id") or c.get("_id") or c.get("camp_id", "")
            if not cid:
                continue
            camp_accounts[cid] = extract_account_emails(c)
            camp_days[cid]     = parse_schedule_days(extract_schedule_days(c))
    except Exception:
        try:
            for _, row in get_recent_campaign_accounts().iterrows():
                camp_accounts.setdefault(row["campaign_id"], []).append(row["account_email"])
            for cid in camp_accounts:
                camp_days[cid] = {0, 1, 2, 3, 4}
        except Exception:
            pass

    capacities, mode, total_pool = compute(campaigns_db, acc_limit, camp_accounts, camp_days)
    return capacities, mode, total_pool, campaigns_db, acc_limit, camp_accounts, camp_days


capacities, mode, total_pool, campaigns_db, acc_limit, camp_accounts, camp_days = load()

paused = [c for c in capacities if "PAUSED" in c.status]
if not paused:
    st.info("Нет паузнутых кампаний.")
    st.stop()

_, col_btn = st.columns([8, 1])
with col_btn:
    if st.button("Refresh"):
        st.cache_data.clear()
        st.rerun()

# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------
col1, col2, col3 = st.columns([3, 2, 1])
with col1:
    options   = {c.campaign_name: c for c in paused}
    sel_name  = st.selectbox("Кампания для запуска", list(options.keys()))
with col2:
    start_dt  = st.date_input("Дата старта", value=date.today() + timedelta(days=1))
with col3:
    days_ahead = st.number_input("Дней вперёд", 7, 90, 30, step=7)

sel = options[sel_name]

# ---------------------------------------------------------------------------
# Recompute with new campaign as ACTIVE (recalculates pool split)
# ---------------------------------------------------------------------------
today = date.today()
dates = [today + timedelta(days=i) for i in range(days_ahead)]

# Baseline (current state)
baseline_sends = project_sends(capacities, dates)
base_totals    = [sum(baseline_sends[c][i] for c in baseline_sends) for i in range(len(dates))]

# Sim: add selected campaign to active pool
sim_caps, sim_mode, _ = compute(
    campaigns_db.copy().assign(
        status=campaigns_db["status"].where(
            campaigns_db["id"] != sel.campaign_id, "ACTIVE"
        )
    ),
    acc_limit, camp_accounts, camp_days,
)
sim_sends = project_sends(
    sim_caps, dates,
    extra_active={sel.campaign_id},
    extra_start_date=start_dt,
)
sim_totals = [sum(sim_sends[c][i] for c in sim_sends) for i in range(len(dates))]

# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------
fig = go.Figure()

fig.add_trace(go.Scatter(
    name="Baseline",
    x=[d.strftime("%Y-%m-%d") for d in dates],
    y=base_totals,
    mode="lines",
    line=dict(color="#4a9eff", width=2, dash="dash"),
    hovertemplate="%{x}<br>Baseline: %{y:,.0f}<extra></extra>",
))

for name, sends in sim_sends.items():
    bar = go.Bar(
        name=name,
        x=[d.strftime("%Y-%m-%d") for d in dates],
        y=sends,
        hovertemplate="%{x}<br>%{fullData.name}: %{y:,.0f}<extra></extra>",
    )
    if name == sel_name:
        bar.marker = dict(color="#ff6b6b", opacity=0.85)
    fig.add_trace(bar)

fig.add_trace(go.Scatter(
    name="Итого (sim)",
    x=[d.strftime("%Y-%m-%d") for d in dates],
    y=sim_totals,
    mode="lines+markers",
    line=dict(color="white", width=2),
    marker=dict(size=4),
    hovertemplate="%{x}<br>Итого: %{y:,.0f}<extra></extra>",
))

fig.add_vline(
    x=start_dt.strftime("%Y-%m-%d"),
    line_dash="dot",
    line_color="#ff6b6b",
    annotation_text=f"Старт: {start_dt}",
    annotation_position="top right",
    annotation_font_color="#ff6b6b",
)

fig.update_layout(
    barmode="stack",
    title=f"Симуляция: '{sel_name}' с {start_dt} | режим: {sim_mode.upper()}",
    xaxis_title="Дата",
    yaxis_title="Emails/день",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    height=520,
    plot_bgcolor="#0e1117",
    paper_bgcolor="#0e1117",
    font=dict(color="white"),
    xaxis=dict(gridcolor="#2a2a2a"),
    yaxis=dict(gridcolor="#2a2a2a"),
)

st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Impact
# ---------------------------------------------------------------------------
st.subheader("Impact")

sim_cap_obj = next((c for c in sim_caps if c.campaign_id == sel.campaign_id), None)
new_cap = sim_cap_obj.daily_cap if sim_cap_obj else 0

num_active_before = len([c for c in capacities if c.status == "ACTIVE"])
cap_before = total_pool // num_active_before if num_active_before else 0
cap_after  = total_pool // (num_active_before + 1) if mode == "communism" else new_cap
delta_per_existing = cap_after - cap_before if mode == "communism" else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Лидов в кампании", f"{sel.remaining:,}")
c2.metric("Cap/день новой кампании", new_cap)
c3.metric("ETA (дней)", sim_cap_obj.eta_days if sim_cap_obj and sim_cap_obj.eta_days else "—")
c4.metric(
    "Изменение cap существующих",
    f"{delta_per_existing:+d}/день" if mode == "communism" else "N/A (split)",
    help="На сколько уменьшится daily cap у каждой текущей активной кампании"
)

new_emails = sum(
    sim_sends.get(sel_name, [0] * len(dates))[i]
    for i, d in enumerate(dates) if d >= start_dt
)
st.info(
    f"Новая кампания отправит ~**{new_emails:,.0f}** писем за {days_ahead} дней "
    f"(pool {total_pool}/день ÷ {num_active_before + 1} активных кампаний = **{new_cap}/день**)."
)

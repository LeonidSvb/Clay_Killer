import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date, timedelta
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from db import get_campaigns, get_email_accounts, get_recent_campaign_accounts
from api import get_all_campaigns_full, extract_account_emails, extract_schedule_days, parse_schedule_days
from capacity import compute, project_sends

st.set_page_config(page_title="Timeline", layout="wide")
st.title("Timeline — Projected Sends")


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
    return capacities, mode, total_pool


capacities, mode, total_pool = load()

_, col_btn = st.columns([8, 1])
with col_btn:
    if st.button("Refresh"):
        st.cache_data.clear()
        st.rerun()

days_ahead = st.slider("Дней вперёд", 7, 90, 30, step=7)

today = date.today()
dates = [today + timedelta(days=i) for i in range(days_ahead)]

chart_data = project_sends(capacities, dates)

# ---------------------------------------------------------------------------
# Plotly stacked bar
# ---------------------------------------------------------------------------
fig = go.Figure()

for name, sends in chart_data.items():
    fig.add_trace(go.Bar(
        name=name,
        x=[d.strftime("%Y-%m-%d") for d in dates],
        y=sends,
        hovertemplate="%{x}<br>%{fullData.name}: %{y:,.0f}<extra></extra>",
    ))

totals = [sum(chart_data[c][i] for c in chart_data) for i in range(len(dates))]
fig.add_trace(go.Scatter(
    name="Итого",
    x=[d.strftime("%Y-%m-%d") for d in dates],
    y=totals,
    mode="lines+markers",
    line=dict(color="white", width=2, dash="dot"),
    marker=dict(size=4),
    hovertemplate="%{x}<br>Итого: %{y:,.0f}<extra></extra>",
))

fig.update_layout(
    barmode="stack",
    title=f"Projected sends — pool {total_pool}/день, режим: {mode.upper()}",
    xaxis_title="Дата",
    yaxis_title="Emails/день",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    height=500,
    plot_bgcolor="#0e1117",
    paper_bgcolor="#0e1117",
    font=dict(color="white"),
    xaxis=dict(gridcolor="#2a2a2a"),
    yaxis=dict(gridcolor="#2a2a2a"),
)

st.plotly_chart(fig, use_container_width=True)

# Weekly table
st.subheader("По неделям")
weeks: dict[str, dict[str, float]] = {}
for i, d in enumerate(dates):
    label = f"Нед {d.isocalendar().week} ({d.strftime('%d %b')})"
    for name in chart_data:
        weeks.setdefault(label, {}).setdefault(name, 0)
        weeks[label][name] += chart_data[name][i]
    weeks.setdefault(label, {}).setdefault("ИТОГО", 0)
    weeks[label]["ИТОГО"] += totals[i]

weeks_df = pd.DataFrame(weeks).T
if "ИТОГО" in weeks_df.columns:
    weeks_df = weeks_df[[c for c in weeks_df.columns if c != "ИТОГО"] + ["ИТОГО"]]

st.dataframe(
    weeks_df.style.format("{:,.0f}").background_gradient(cmap="Blues", axis=None),
    use_container_width=True,
)

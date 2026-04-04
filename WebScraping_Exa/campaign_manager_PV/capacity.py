"""
Capacity calculation engine.

Auto-detects two modes:
  COMMUNISM  — all accounts shared across all campaigns (sum of caps >> pool)
               each active campaign gets  total_pool / N  sends per day
  SPLIT      — accounts divided between campaigns
               each campaign gets sum of its own account limits

Detection: if sum(per-campaign caps) > pool * COMMUNISM_THRESHOLD → communism mode.
"""

import math
from dataclasses import dataclass

COMMUNISM_THRESHOLD = 1.5   # overlap ratio to trigger communism mode


@dataclass
class CampaignCapacity:
    campaign_id:   str
    campaign_name: str
    status:        str
    daily_cap:     int          # effective sends per day
    remaining:     int          # leads not yet contacted
    schedule_days: set[int]     # Python weekday ints (0=Mon)
    eta_days:      int | None   # working days to exhaust remaining leads
    mode:          str          # "communism" | "split"


def compute(
    campaigns_db,           # pd.DataFrame from db.get_campaigns()
    acc_limit: dict,        # {account_email: daily_limit}
    camp_accounts: dict,    # {campaign_id: [account_emails]}  (from API or fallback)
    camp_days: dict,        # {campaign_id: set[int]}
) -> tuple[list[CampaignCapacity], str, int]:
    """
    Returns (capacities, mode, total_pool).
    """
    total_pool = sum(acc_limit.values())

    active_df = campaigns_db[campaigns_db["status"] == "ACTIVE"]
    num_active = len(active_df)

    # Per-campaign raw caps (ignoring sharing)
    per_camp_cap: dict[str, int] = {}
    for _, row in active_df.iterrows():
        cid  = row["id"]
        accs = camp_accounts.get(cid, [])
        raw  = sum(acc_limit.get(a, 0) for a in accs)
        # Respect campaign-level daily_limit override if set and lower
        cl = row.get("daily_limit") or 0
        per_camp_cap[cid] = int(min(raw, cl) if cl and cl < raw else raw)

    sum_of_caps = sum(per_camp_cap.values())

    # Auto-detect mode
    if total_pool > 0 and sum_of_caps > total_pool * COMMUNISM_THRESHOLD:
        mode = "communism"
    else:
        mode = "split"

    results = []
    for _, row in campaigns_db[campaigns_db["status"].isin(["ACTIVE", "PAUSED"])].iterrows():
        cid    = row["id"]
        status = row["status"]
        days   = camp_days.get(cid, {0, 1, 2, 3, 4})

        if status == "ACTIVE":
            if mode == "communism":
                cap = math.ceil(total_pool / num_active) if num_active else 0
                # Still respect campaign-level override
                cl = row.get("daily_limit") or 0
                if cl and cl < cap:
                    cap = cl
            else:
                cap = per_camp_cap.get(cid, 0)
        else:
            # PAUSED — compute hypothetical cap if it were active
            if mode == "communism":
                cap = math.ceil(total_pool / (num_active + 1)) if num_active >= 0 else 0
            else:
                accs = camp_accounts.get(cid, [])
                raw  = sum(acc_limit.get(a, 0) for a in accs)
                cl   = row.get("daily_limit") or 0
                cap  = int(min(raw, cl) if cl and cl < raw else raw)

        remaining = max(0, (row["lead_count"] or 0) - (row["lead_contacted_count"] or 0))
        eta = math.ceil(remaining / cap) if cap > 0 and remaining > 0 else (0 if remaining == 0 else None)

        results.append(CampaignCapacity(
            campaign_id=cid,
            campaign_name=row["name"],
            status=status,
            daily_cap=cap,
            remaining=remaining,
            schedule_days=days,
            eta_days=eta,
            mode=mode if status == "ACTIVE" else f"{mode}*",
        ))

    return results, mode, total_pool


def project_sends(
    capacities: list[CampaignCapacity],
    dates: list,
    extra_active: set[str] | None = None,  # campaign_ids to treat as ACTIVE (for simulator)
    extra_start_date=None,
) -> dict[str, list[float]]:
    """
    Project daily sends per campaign over a list of dates.
    Returns {campaign_name: [sends_per_day, ...]}.
    """
    result = {}
    for c in capacities:
        is_active = c.status == "ACTIVE"
        if extra_active and c.campaign_id in extra_active:
            is_active = True

        if not is_active:
            continue

        sends = []
        cumulative = 0
        for d in dates:
            started = extra_start_date is None or d >= extra_start_date or c.status == "ACTIVE"
            if started and d.weekday() in c.schedule_days and cumulative < c.remaining:
                day_sends = min(c.daily_cap, c.remaining - cumulative)
                sends.append(float(day_sends))
                cumulative += day_sends
            else:
                sends.append(0.0)
        result[c.campaign_name] = sends

    return result

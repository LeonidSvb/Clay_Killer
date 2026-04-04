import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_URL  = os.getenv("PLUSVIBE_BASE_URL", "https://api.plusvibe.ai/api/v1")
API_KEY   = os.getenv("PLUSVIBE_API_KEY")
WS_ID     = os.getenv("PLUSVIBE_WORKSPACE_ID")

HEADERS = {"x-api-key": API_KEY}


def _get(path: str, **params) -> dict | list:
    params["workspace_id"] = WS_ID
    r = requests.get(f"{BASE_URL}{path}", headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def get_campaigns_full(status: str = None) -> list[dict]:
    """Returns full campaign objects including email_accounts[] and schedule."""
    params = {"limit": 100, "skip": 0, "campaign_type": "parent"}
    if status:
        params["status"] = status
    result = _get("/campaign/list-all", **params)
    return result if isinstance(result, list) else result.get("campaigns", result.get("data", []))


def get_all_campaigns_full() -> list[dict]:
    campaigns = []
    for status in ("ACTIVE", "PAUSED"):
        try:
            campaigns.extend(get_campaigns_full(status))
        except Exception:
            pass
    return campaigns


def extract_account_emails(campaign: dict) -> list[str]:
    """Extract list of account email strings from a full campaign object."""
    raw = campaign.get("email_accounts", [])
    if not raw:
        return []
    if isinstance(raw[0], dict):
        return [a.get("email", "") for a in raw if a.get("email")]
    return [a for a in raw if isinstance(a, str) and a]


def extract_schedule_days(campaign: dict) -> list:
    """Return raw schedule days list from campaign object."""
    sched = campaign.get("schedule", {})
    return sched.get("days", [])


# ---------------------------------------------------------------------------
# Day parsing helpers
# ---------------------------------------------------------------------------

_DAY_MAP = {
    "MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6,
    "MONDAY": 0, "TUESDAY": 1, "WEDNESDAY": 2, "THURSDAY": 3,
    "FRIDAY": 4, "SATURDAY": 5, "SUNDAY": 6,
    0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6,
}

DEFAULT_DAYS = {0, 1, 2, 3, 4}  # Mon–Fri fallback


def parse_schedule_days(days: list) -> set[int]:
    if not days:
        return DEFAULT_DAYS
    result = set()
    for d in days:
        key = d.upper().strip() if isinstance(d, str) else d
        if key in _DAY_MAP:
            result.add(_DAY_MAP[key])
    return result if result else DEFAULT_DAYS

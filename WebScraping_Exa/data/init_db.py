"""
data/init_db.py

Creates leads.db (SQLite) with two tables:
  companies — one row per unique domain (all expensive enrichments go here)
  leads     — one row per email (personal fields + FK to company)

Import order:
  1. eu_4500 (has website_summary + extraction + mx)
  2. us_recruit_clean_1634 (has website_summary)
  3. us_enriched_500 (has LLM extraction)
  4. canada_usable_296 (full Apollo)
  5. Canada logistics (recruit vertical = logistic)
  6. campaigns/ icebreaker CSVs (fill extraction fields from our pipeline)

Usage:
    py data/init_db.py              -- full import
    py data/init_db.py --reset      -- drop + recreate before import
    py data/init_db.py --stats      -- just print fill rates, no import
"""

import argparse
import csv
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DB_PATH   = Path(__file__).parent / "leads.db"
DATA_DIR  = Path(__file__).parent
CAMP_DIR  = Path(__file__).parent.parent / "icebreakers_round_robin" / "campaigns"


# ── schema ────────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS companies (
    domain                  TEXT PRIMARY KEY,
    company_name            TEXT,
    clean_company           TEXT,
    company_website         TEXT,
    company_linkedin_url    TEXT,
    company_short_description TEXT,
    company_seo_description TEXT,
    keywords                TEXT,
    company_technologies    TEXT,
    employees_count         INTEGER,
    company_annual_revenue  TEXT,
    company_founded_year    TEXT,
    company_total_funding   TEXT,

    -- MX (per domain, not per lead)
    mx_provider             TEXT,
    mx_checked_at           TEXT,

    -- web scraping
    website_js_type         TEXT,
    website_pages_raw       TEXT,   -- JSON [{url,text,chars,source}]
    website_summary         TEXT,
    website_scraped_at      TEXT,
    website_scrape_source   TEXT,

    -- LLM extraction
    primary_service         TEXT,
    sub_industry            TEXT,
    client_profile          TEXT,
    extractability          TEXT,
    extracted_at            TEXT,
    extraction_raw          TEXT,   -- JSON: confidence, signals, geography, etc.

    created_at              TEXT DEFAULT (datetime('now')),
    updated_at              TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS leads (
    email                   TEXT PRIMARY KEY,
    domain                  TEXT REFERENCES companies(domain),

    -- personal
    first_name              TEXT,
    last_name               TEXT,
    full_name               TEXT,
    linkedin_url            TEXT,
    title                   TEXT,
    headline                TEXT,
    seniority               TEXT,
    city                    TEXT,
    state                   TEXT,
    country                 TEXT,
    industry                TEXT,
    email_catchall          INTEGER,  -- 0/1

    -- email validation
    email_validation_status  TEXT,   -- valid/catch_all/risky/invalid/unknown
    email_validation_service TEXT,   -- mailso/lemverifier/plusvibe
    email_validated_at       TEXT,

    -- meta
    lead_vertical           TEXT,    -- recruit/logistic
    source_file             TEXT,
    plusvibe_status         TEXT,
    plusvibe_synced_at      TEXT,
    created_at              TEXT DEFAULT (datetime('now')),
    updated_at              TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_leads_domain    ON leads(domain);
CREATE INDEX IF NOT EXISTS idx_leads_country   ON leads(country);
CREATE INDEX IF NOT EXISTS idx_leads_vertical  ON leads(lead_vertical);
CREATE INDEX IF NOT EXISTS idx_co_service      ON companies(primary_service);
CREATE INDEX IF NOT EXISTS idx_co_sub          ON companies(sub_industry);
CREATE INDEX IF NOT EXISTS idx_co_mx           ON companies(mx_provider);
"""


# ── helpers ───────────────────────────────────────────────────────────────────

def extract_domain(url: str) -> str | None:
    if not url:
        return None
    url = url.strip().lower()
    url = re.sub(r'^https?://', '', url)
    url = url.split('/')[0].split('?')[0]
    url = re.sub(r'^www\.', '', url)
    return url or None


def clean(v) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    return v if v and v.lower() not in ('nan', 'none', '') else None


def to_int(v) -> int | None:
    try:
        return int(str(v).replace(',', '').strip())
    except Exception:
        return None


def upsert_company(cur: sqlite3.Cursor, domain: str, data: dict):
    """Insert or update company — only fills empty fields, never overwrites."""
    cur.execute("SELECT domain FROM companies WHERE domain = ?", (domain,))
    if cur.fetchone():
        # only update fields that are currently NULL
        updates = []
        vals = []
        for col, val in data.items():
            if col == "domain" or val is None:
                continue
            cur.execute(f"SELECT {col} FROM companies WHERE domain = ?", (domain,))
            row = cur.fetchone()
            if row and row[0] is None:
                updates.append(f"{col} = ?")
                vals.append(val)
        if updates:
            vals.append(datetime('now').isoformat() if False else datetime.now().isoformat())
            vals.append(domain)
            cur.execute(
                f"UPDATE companies SET {', '.join(updates)}, updated_at = ? WHERE domain = ?",
                vals
            )
    else:
        data["domain"] = domain
        cols = ', '.join(data.keys())
        placeholders = ', '.join(['?'] * len(data))
        cur.execute(f"INSERT OR IGNORE INTO companies ({cols}) VALUES ({placeholders})", list(data.values()))


def upsert_lead(cur: sqlite3.Cursor, email: str, data: dict):
    """Insert or update lead — only fills empty fields."""
    cur.execute("SELECT email FROM leads WHERE email = ?", (email,))
    if cur.fetchone():
        updates = []
        vals = []
        for col, val in data.items():
            if col == "email" or val is None:
                continue
            cur.execute(f"SELECT {col} FROM leads WHERE email = ?", (email,))
            row = cur.fetchone()
            if row and row[0] is None:
                updates.append(f"{col} = ?")
                vals.append(val)
        if updates:
            vals.append(datetime.now().isoformat())
            vals.append(email)
            cur.execute(
                f"UPDATE leads SET {', '.join(updates)}, updated_at = ? WHERE email = ?",
                vals
            )
    else:
        data["email"] = email
        cols = ', '.join(data.keys())
        placeholders = ', '.join(['?'] * len(data))
        cur.execute(f"INSERT OR IGNORE INTO leads ({cols}) VALUES ({placeholders})", list(data.values()))


# ── column normalizers ────────────────────────────────────────────────────────

_MX_NORM = {
    "google workspace": "google",
    "google_workspace": "google",
    "google":           "google",
    "google.com":       "google",
    "microsoft 365":    "microsoft",
    "microsoft":        "microsoft",
    "office 365":       "microsoft",
    "outlook":          "microsoft",
    "mimecast":         "mimecast",
    "proofpoint":       "proofpoint",
    "proofpoint essentials": "proofpoint",
    "no mx":            "no_mx",
    "custom / other":   "other",
    "custom/other":     "other",
    "others":           "other",
}

def normalize_mx(val: str | None) -> str | None:
    if not val:
        return None
    return _MX_NORM.get(val.strip().lower(), val.strip().lower())


def row_to_company(row: dict) -> dict:
    website = (clean(row.get("Company Website")) or
               clean(row.get("domain")) or
               clean(row.get("company_website")))
    domain = extract_domain(website)
    if not domain:
        return {}

    extraction_fields = {}
    for f in ["confidence", "detected_signals", "reasoning", "geography",
              "company_type", "business_model", "specificity",
              "secondary_services", "secondary_industries",
              "primary_industry", "company_stage"]:
        v = clean(row.get(f))
        if v:
            extraction_fields[f] = v

    ws = (clean(row.get("Website summary")) or
          clean(row.get("Website Summary")) or
          clean(row.get("Website Summary (100%)")) or
          clean(row.get("website_summary")))

    raw_mx = (clean(row.get("mx_provider")) or
              clean(row.get("Provider")) or
              clean(row.get("_mx_provider")))

    return {
        "domain":                   domain,
        "company_name":             clean(row.get("Company Name") or row.get("COMPANY NAME")),
        "clean_company":            clean(row.get("Clean Company") or row.get("clean_company")),
        "company_website":          website,
        "company_linkedin_url":     clean(row.get("Company Linkedin") or row.get("company_linkedin_url")),
        "company_short_description":clean(row.get("Company Short Description")),
        "company_seo_description":  clean(row.get("Company SEO Description")),
        "keywords":                 clean(row.get("Keywords") or row.get("Company Keywords")),
        "company_technologies":     clean(row.get("Company Technologies")),
        "employees_count":          to_int(row.get("Employees Count") or row.get("employees_count")),
        "company_annual_revenue":   clean(row.get("Company Annual Revenue Clean") or
                                          clean(row.get("Company Annual Revenue"))),
        "company_founded_year":     clean(row.get("Company Founded Year")),
        "company_total_funding":    clean(row.get("Company Total Funding Clean") or
                                         row.get("Company Total Funding")),
        "mx_provider":              normalize_mx(raw_mx),
        "website_summary":          ws,
        "primary_service":          clean(row.get("primary_service")),
        "sub_industry":             clean(row.get("sub_industry")),
        "client_profile":           clean(row.get("client_profile")),
        "extractability":           clean(row.get("extractability")),
        "extraction_raw":           json.dumps(extraction_fields, ensure_ascii=False) if extraction_fields else None,
    }


def row_to_lead(row: dict, vertical: str, source: str) -> dict:
    email = clean(row.get("Email") or row.get("email"))
    if not email or "@" not in email:
        return {}

    website = (clean(row.get("Company Website")) or
               clean(row.get("domain")) or
               clean(row.get("company_website")))
    domain = extract_domain(website)

    catchall_raw = clean(row.get("Email Domain Catchall") or row.get("email_catchall"))
    catchall = None
    if catchall_raw:
        catchall = 1 if catchall_raw.lower() in ("true", "yes", "1") else 0

    return {
        "email":         email,
        "domain":        domain,
        "first_name":    clean(row.get("First Name") or row.get("first_name")),
        "last_name":     clean(row.get("Last Name") or row.get("last_name")),
        "full_name":     clean(row.get("Full Name") or row.get("full_name")),
        "linkedin_url":  clean(row.get("LinkedIn") or row.get("linkedin_url")),
        "title":         clean(row.get("Title") or row.get("title")),
        "headline":      clean(row.get("Headline") or row.get("headline")),
        "seniority":     clean(row.get("Seniority") or row.get("seniority")),
        "city":          clean(row.get("City") or row.get("city")),
        "state":         clean(row.get("State") or row.get("state")),
        "country":       _infer_country(row),
        "industry":      clean(row.get("Industry") or row.get("industry")),
        "email_catchall":catchall,
        "lead_vertical": vertical,
        "source_file":   source,
        # validation: Plusvibe-sent leads with non-bounce status = valid
        "email_validation_status":  _infer_validation(row),
        "email_validation_service": _infer_validation_service(row),
    }


def _infer_country(row: dict) -> str | None:
    c = clean(row.get("Country") or row.get("country") or row.get("Company Country"))
    if c:
        return c
    # US all_leads has State but no Country — infer
    if clean(row.get("State")):
        return "United States"
    return None


def _infer_validation(row: dict) -> str | None:
    """Infer validation from available signals."""
    # EU 4500 has 'Status Email' field
    status = clean(row.get("Status Email") or row.get("status_email"))
    if status:
        s = status.lower()
        if "valid" in s:    return "valid"
        if "catch" in s:    return "catch_all"
        if "risky" in s:    return "risky"
        if "invalid" in s:  return "invalid"

    # has website summary = was scraped = apollo validated
    ws = clean(row.get("Website summary") or row.get("Website Summary"))
    if ws:
        return "valid"

    return None


def _infer_validation_service(row: dict) -> str | None:
    status = clean(row.get("Status Email") or row.get("status_email"))
    if status:
        return "apollo"
    ws = clean(row.get("Website summary") or row.get("Website Summary"))
    if ws:
        return "apollo"
    return None


# ── import sources ────────────────────────────────────────────────────────────

DOWNLOADS = Path.home() / "Downloads"

SOURCES = [
    # (file_path, vertical, encoding)
    # --- existing ---
    (DATA_DIR / "_Europe+ recruit - 4500_All.csv",                          "recruit",  "utf-8"),
    (DATA_DIR / "us_recruit_clean_1634.csv",                                "recruit",  "utf-8"),
    (DATA_DIR / "us_enriched_500.csv",                                      "recruit",  "utf-8-sig"),
    (DATA_DIR / "US recruit 10-100  - all_leads (1).csv",                   "recruit",  "utf-8"),
    (DATA_DIR / "canada_usable_296.csv",                                    "recruit",  "utf-8"),
    (DATA_DIR / "Canada+ - logistic 10-100 - 500_G+Ot (1).csv",            "logistic", "latin-1"),
    # --- new ---
    (DOWNLOADS / "_US+ recruit 10-100  - 10500_initial_list.csv",           "recruit",  "utf-8-sig"),
    (DOWNLOADS / "Australia+  recruit 10-100  - aus_email (1).csv",         "recruit",  "utf-8-sig"),
    (DOWNLOADS / "Canada+  recruit 10-100  - canada_ms.csv",                "recruit",  "utf-8-sig"),
]

# Mailso validation result → our status
_MAILSO_MAP = {
    "deliverable":   "valid",
    "undeliverable": "invalid",
    "risky":         "risky",
    "unknown":       "unknown",
}


def import_csv(con: sqlite3.Connection, path: Path, vertical: str, encoding: str):
    if not path.exists():
        print(f"  SKIP (not found): {path.name}")
        return 0, 0

    try:
        rows = list(csv.DictReader(open(path, encoding=encoding)))
    except Exception as e:
        print(f"  ERROR reading {path.name}: {e}")
        return 0, 0

    co_count = 0
    lead_count = 0
    cur = con.cursor()

    for row in rows:
        co_data = row_to_company(row)
        if co_data.get("domain"):
            upsert_company(cur, co_data["domain"], co_data)
            co_count += 1

        lead_data = row_to_lead(row, vertical, path.name)
        if lead_data.get("email"):
            upsert_lead(cur, lead_data["email"], lead_data)
            lead_count += 1

    con.commit()
    print(f"  {path.name}: {lead_count} leads, {co_count} companies")
    return lead_count, co_count


def import_mailso(con: sqlite3.Connection):
    """Import Mailso validation results — update email_validation_status per lead."""
    path = DOWNLOADS / "_US+ recruit 10-100  - all_mailso.csv"
    if not path.exists():
        print(f"  SKIP mailso (not found): {path.name}")
        return

    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    cur = con.cursor()
    updated = 0
    inserted = 0

    for row in rows:
        email = clean(row.get("Email") or row.get("email"))
        if not email or "@" not in email:
            continue

        result  = clean(row.get("Result", ""))
        status  = _MAILSO_MAP.get((result or "").lower(), "unknown")
        domain_raw = clean(row.get("Domain") or row.get("domain"))
        domain  = domain_raw.lower().strip() if domain_raw else None
        mx_raw  = clean(row.get("MxRecord") or row.get("Provider"))
        mx      = normalize_mx(mx_raw)
        score   = clean(row.get("Score"))
        catch   = row.get("IsvNocatchall", "").strip().upper()
        catchall_val = 0 if catch == "TRUE" else (1 if catch == "FALSE" else None)

        # update lead if exists
        cur.execute("SELECT email FROM leads WHERE email = ?", (email,))
        if cur.fetchone():
            cur.execute("""
                UPDATE leads SET
                    email_validation_status  = COALESCE(email_validation_status, ?),
                    email_validation_service = COALESCE(email_validation_service, 'mailso'),
                    email_validated_at       = COALESCE(email_validated_at, datetime('now')),
                    email_catchall           = COALESCE(email_catchall, ?)
                WHERE email = ?
            """, (status, catchall_val, email))
            updated += 1
        else:
            # lead not in DB yet — insert minimal record + link to company
            cur.execute("""
                INSERT OR IGNORE INTO leads
                    (email, domain, email_validation_status, email_validation_service,
                     email_validated_at, email_catchall, lead_vertical, source_file)
                VALUES (?, ?, ?, 'mailso', datetime('now'), ?, 'recruit', 'mailso')
            """, (email, domain, status, catchall_val))
            inserted += 1

        # update company mx if missing
        if domain and mx:
            cur.execute("""
                UPDATE companies SET
                    mx_provider  = COALESCE(mx_provider, ?),
                    mx_checked_at = COALESCE(mx_checked_at, datetime('now'))
                WHERE domain = ?
            """, (mx, domain))

    con.commit()
    valid   = sum(1 for r in rows if r.get("Result","").lower() == "deliverable")
    invalid = sum(1 for r in rows if r.get("Result","").lower() == "undeliverable")
    risky   = sum(1 for r in rows if r.get("Result","").lower() == "risky")
    print(f"  Mailso: {len(rows)} rows | valid={valid} invalid={invalid} risky={risky}")
    print(f"    updated={updated} leads, inserted={inserted} new leads")


def import_campaign_extractions(con: sqlite3.Connection):
    """Fill extraction fields from campaign CSVs (our pipeline output)."""
    cur = con.cursor()
    updated = 0

    for f in CAMP_DIR.glob("*.csv"):
        if "PLAYBOOK" in f.name:
            continue
        try:
            rows = list(csv.DictReader(open(f, encoding="utf-8")))
        except Exception:
            continue

        for row in rows:
            website = clean(row.get("_company_website") or row.get("company_name"))
            domain = extract_domain(website)
            if not domain:
                continue
            svc = clean(row.get("primary_service"))
            sub = clean(row.get("sub_industry"))
            cp  = clean(row.get("client_profile"))
            if svc:
                cur.execute("""
                    UPDATE companies SET
                        primary_service = COALESCE(primary_service, ?),
                        sub_industry    = COALESCE(sub_industry, ?),
                        client_profile  = COALESCE(client_profile, ?)
                    WHERE domain = ?
                """, (svc, sub, cp, domain))
                updated += 1

    con.commit()
    print(f"  Campaign extractions: {updated} company rows updated")


# ── stats ─────────────────────────────────────────────────────────────────────

def print_stats(con: sqlite3.Connection):
    cur = con.cursor()

    cur.execute("SELECT COUNT(*) FROM leads")
    total_leads = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM companies")
    total_co = cur.fetchone()[0]

    print(f"\n{'='*55}")
    print(f"LEADS: {total_leads}   COMPANIES: {total_co}")
    print(f"{'='*55}")

    lead_cols = [
        "first_name", "linkedin_url", "headline", "country",
        "email_validation_status", "email_catchall",
    ]
    print("\nLEADS fill rate:")
    for col in lead_cols:
        cur.execute(f"SELECT COUNT(*) FROM leads WHERE {col} IS NOT NULL")
        n = cur.fetchone()[0]
        print(f"  {col:<30} {n:>6}  {n/max(total_leads,1)*100:>5.1f}%")

    co_cols = [
        "company_website", "company_short_description", "keywords",
        "mx_provider", "website_summary", "primary_service",
        "sub_industry", "client_profile", "extraction_raw",
    ]
    print("\nCOMPANIES fill rate:")
    for col in co_cols:
        cur.execute(f"SELECT COUNT(*) FROM companies WHERE {col} IS NOT NULL")
        n = cur.fetchone()[0]
        print(f"  {col:<30} {n:>6}  {n/max(total_co,1)*100:>5.1f}%")

    print("\nLeads by vertical:")
    for row in cur.execute("SELECT lead_vertical, COUNT(*) FROM leads GROUP BY lead_vertical"):
        print(f"  {row[0]}: {row[1]}")

    print("\nLeads by country (top 10):")
    for row in cur.execute("SELECT country, COUNT(*) n FROM leads GROUP BY country ORDER BY n DESC LIMIT 10"):
        print(f"  {row[0]}: {row[1]}")

    print("\nMX provider breakdown (companies):")
    for row in cur.execute("SELECT mx_provider, COUNT(*) n FROM companies WHERE mx_provider IS NOT NULL GROUP BY mx_provider ORDER BY n DESC"):
        print(f"  {row[0]}: {row[1]}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Drop and recreate DB")
    parser.add_argument("--stats", action="store_true", help="Print stats only")
    args = parser.parse_args()

    if args.stats and DB_PATH.exists():
        con = sqlite3.connect(DB_PATH)
        print_stats(con)
        con.close()
        return

    if args.reset and DB_PATH.exists():
        DB_PATH.unlink()
        print("Dropped existing DB")

    con = sqlite3.connect(DB_PATH)
    con.executescript(DDL)
    con.commit()
    print(f"DB: {DB_PATH}")

    if not args.stats:
        print("\nImporting CSV sources...")
        total_leads = 0
        for path, vertical, enc in SOURCES:
            l, _ = import_csv(con, path, vertical, enc)
            total_leads += l

        print("\nImporting Mailso validation...")
        import_mailso(con)

        print("\nImporting campaign extraction results...")
        import_campaign_extractions(con)

    print_stats(con)
    con.close()


if __name__ == "__main__":
    main()

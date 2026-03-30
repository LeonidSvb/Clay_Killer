"""
MX Provider Checker — Method 1 (DoH) + Method 2 (dnspython)
Adds two columns: mx_provider_doh, mx_provider_dns
"""

import asyncio
import csv
import sys
from pathlib import Path

import aiohttp
import dns.asyncresolver
import dns.exception

INPUT  = r"C:\Users\79818\Downloads\canada - logistic - valid_1700.csv"
OUTPUT = r"C:\Users\79818\Downloads\canada - logistic - valid_1700_mx.csv"

CONCURRENCY = 50

# Provider classification patterns (order matters — more specific first)
PROVIDER_PATTERNS = [
    ("Google",      ["aspmx.l.google.com", "googlemail.com", "smtp.google.com",
                     "aspmx.l.google", "alt1.aspmx", "alt2.aspmx",
                     "aspmx2.googlemail", "aspmx3.googlemail",
                     "aspmx4.googlemail", "aspmx5.googlemail"]),
    ("Microsoft",   ["mail.protection.outlook.com", "olc.protection.outlook.com",
                     "outlook.com", "hotmail.com"]),
    ("Mimecast",    ["mimecast.com"]),
    ("Proofpoint",  ["pphosted.com", "gslb.pphosted.com"]),
    ("Zoho",        ["zoho.com", "zoho.eu", "zoho.in"]),
    ("ProtonMail",  ["protonmail.ch"]),
    ("Yahoo",       ["yahoodns.net", "yahoo.com", "yahoomail.com"]),
    ("Barracuda",   ["barracudanetworks.com"]),
    ("Sendgrid",    ["sendgrid.net"]),
    ("Mailgun",     ["mailgun.org"]),
]

def classify(mx_records: list[str]) -> str:
    if not mx_records:
        return "No MX"
    combined = " ".join(mx_records).lower()
    for provider, patterns in PROVIDER_PATTERNS:
        if any(p.lower() in combined for p in patterns):
            return provider
    return "Other"

def extract_domain(email: str) -> str:
    email = email.strip().lower()
    if "@" in email:
        return email.split("@", 1)[1]
    return ""


# ---------- Method 1: DNS-over-HTTPS (Google DoH) ----------

async def doh_mx(session: aiohttp.ClientSession, domain: str, sem: asyncio.Semaphore) -> list[str]:
    url = f"https://dns.google/resolve?name={domain}&type=MX"
    async with sem:
        for attempt in range(3):
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(1 * (attempt + 1))
                        continue
                    data = await resp.json(content_type=None)
                    answers = data.get("Answer", [])
                    # MX record data format: "10 aspmx.l.google.com."
                    return [a["data"].split(" ", 1)[-1].rstrip(".") for a in answers if a.get("type") == 15]
            except Exception:
                await asyncio.sleep(0.5)
    return []

async def run_doh(domains: list[str]) -> dict[str, str]:
    sem = asyncio.Semaphore(CONCURRENCY)
    results = {}
    connector = aiohttp.TCPConnector(limit=CONCURRENCY)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = {domain: asyncio.create_task(doh_mx(session, domain, sem)) for domain in domains}
        done = 0
        total = len(tasks)
        for domain, task in tasks.items():
            mx = await task
            results[domain] = classify(mx)
            done += 1
            if done % 100 == 0:
                print(f"  DoH: {done}/{total}", flush=True)
    return results


# ---------- Method 2: dnspython native DNS ----------

async def dns_mx(domain: str, resolver: dns.asyncresolver.Resolver, sem: asyncio.Semaphore) -> list[str]:
    async with sem:
        for attempt in range(3):
            try:
                answers = await resolver.resolve(domain, "MX")
                return [str(r.exchange).rstrip(".") for r in answers]
            except (dns.exception.Timeout, dns.resolver.NoNameservers):
                await asyncio.sleep(0.3 * (attempt + 1))
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
                return []
            except Exception:
                return []
    return []

async def run_dns(domains: list[str]) -> dict[str, str]:
    sem = asyncio.Semaphore(CONCURRENCY)
    resolver = dns.asyncresolver.Resolver()
    resolver.nameservers = ["8.8.8.8", "1.1.1.1", "8.8.4.4"]
    resolver.timeout = 5
    resolver.lifetime = 8
    results = {}
    tasks = {domain: asyncio.create_task(dns_mx(domain, resolver, sem)) for domain in domains}
    done = 0
    total = len(tasks)
    for domain, task in tasks.items():
        mx = await task
        results[domain] = classify(mx)
        done += 1
        if done % 100 == 0:
            print(f"  DNS: {done}/{total}", flush=True)
    return results


# ---------- Main ----------

async def main():
    # Read CSV
    rows = []
    fieldnames = []
    with open(INPUT, encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            rows.append(row)

    print(f"Loaded {len(rows)} rows")

    # Collect unique domains
    domains_set = set()
    for row in rows:
        email = row.get("Email", "").strip()
        domain = extract_domain(email)
        if domain:
            domains_set.add(domain)

    domains = list(domains_set)
    print(f"Unique domains: {len(domains)}")

    # Method 1: DoH
    print("Running Method 1 (DNS-over-HTTPS)...")
    doh_results = await run_doh(domains)
    print(f"DoH done. Sample: {list(doh_results.items())[:5]}")

    # Method 2: dnspython
    print("Running Method 2 (dnspython)...")
    dns_results = await run_dns(domains)
    print(f"DNS done. Sample: {list(dns_results.items())[:5]}")

    # Add columns
    new_fieldnames = list(fieldnames) + ["mx_provider_doh", "mx_provider_dns"]
    for row in rows:
        email = row.get("Email", "").strip()
        domain = extract_domain(email)
        row["mx_provider_doh"] = doh_results.get(domain, "No domain") if domain else "No email"
        row["mx_provider_dns"] = dns_results.get(domain, "No domain") if domain else "No email"

    # Write output
    with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved to: {OUTPUT}")

    # Summary stats
    from collections import Counter
    doh_stats = Counter(row["mx_provider_doh"] for row in rows)
    dns_stats = Counter(row["mx_provider_dns"] for row in rows)
    print("\n--- Method 1 (DoH) breakdown ---")
    for k, v in doh_stats.most_common():
        print(f"  {k}: {v}")
    print("\n--- Method 2 (DNS) breakdown ---")
    for k, v in dns_stats.most_common():
        print(f"  {k}: {v}")

    # Agreement check
    agree = sum(1 for r in rows if r["mx_provider_doh"] == r["mx_provider_dns"])
    print(f"\nMethods agree: {agree}/{len(rows)} ({100*agree/len(rows):.1f}%)")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Pitchbook MX Pipeline
Reads target_leads.csv, fixes column misalignment, runs MX check,
saves pitchbook_leads_mx.csv with mx_host + mx_provider columns.

Usage:
    py mx_pipeline.py
    py mx_pipeline.py --rate 30   # requests per second (default 40)
"""

import asyncio
import argparse
import re
import sys
import time
import httpx
import pandas as pd
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).parent
INPUT = BASE / "target_leads.csv"
OUTPUT = BASE / "pitchbook_leads_mx.csv"
DNS_URL = "https://dns.google/resolve"

MX_PATTERNS = [
    (r"protection\.outlook\.com$",   "Microsoft 365"),
    (r"mail\.protection\.outlook",   "Microsoft 365"),
    (r"google\.com$",                "Google Workspace"),
    (r"googlemail\.com$",            "Google Workspace"),
    (r"mimecast\.com$",              "Mimecast"),
    (r"barracudanetworks\.com$",     "Barracuda"),
    (r"pphosted\.com$",              "Proofpoint"),
    (r"proofpoint\.com$",            "Proofpoint"),
    (r"iphmx\.com$",                 "Cisco IronPort"),
    (r"reflexion\.net$",             "Sophos"),
    (r"mailcontrol\.com$",           "Forcepoint"),
    (r"messagelabs\.com$",           "Symantec/MessageLabs"),
    (r"hornetsecurity\.com$",        "Hornetsecurity"),
    (r"mxroute\.com$",               "MXroute"),
    (r"amazonses\.com$",             "Amazon SES"),
    (r"secureserver\.net$",          "GoDaddy"),
    (r"yahoodns\.net$",              "Yahoo"),
    (r"mx\.zoho\.com$",              "Zoho"),
    (r"protonmail\.ch$",             "Proton Mail"),
    (r"mailgun\.org$",               "Mailgun"),
    (r"sendgrid\.net$",              "SendGrid"),
]

GATEWAY_PROVIDERS = {
    "Mimecast", "Barracuda", "Proofpoint", "Cisco IronPort",
    "Sophos", "Forcepoint", "Symantec/MessageLabs", "Hornetsecurity"
}


def mx_classify(mx_hosts: list[str]) -> tuple[str, str]:
    if not mx_hosts:
        return "", "No MX"
    host = mx_hosts[0].lower()
    for pattern, provider in MX_PATTERNS:
        if re.search(pattern, host):
            return mx_hosts[0], provider
    if any(re.search(r"^\d+\.\d+\.\d+\.\d+$", h) for h in mx_hosts):
        return mx_hosts[0], "A-record Fallback"
    return mx_hosts[0], "Custom/Self-hosted"


async def fetch_mx(domain: str, client: httpx.AsyncClient, sem: asyncio.Semaphore) -> tuple[str, str]:
    async with sem:
        try:
            r = await client.get(DNS_URL, params={"name": domain, "type": "MX"}, timeout=8.0)
            data = r.json()
            status = data.get("Status", -1)
            if status == 3:
                return "", "Dead Domain (NXDOMAIN)"
            if status != 0:
                return "", "No MX"
            answers = data.get("Answer", [])
            mx_list = []
            for a in answers:
                if a.get("type") == 15:
                    parts = str(a.get("data", "")).split()
                    if len(parts) >= 2:
                        mx_list.append(parts[1].rstrip(".").lower())
            if not mx_list:
                nss = data.get("Authority", [])
                if not nss:
                    return "", "Dead Domain (NXDOMAIN)"
                return "", "No MX"
            mx_list.sort()
            return mx_classify(mx_list)
        except Exception:
            return "", "Error"


async def run_mx(domains: list[str], rate: int) -> dict[str, tuple[str, str]]:
    sem = asyncio.Semaphore(rate)
    results = {}
    done = 0
    t0 = time.time()

    async def one(domain: str) -> tuple[str, tuple[str, str]]:
        result = await fetch_mx(domain, client, sem)
        return domain, result

    async with httpx.AsyncClient(
        headers={"accept": "application/dns-json"},
        limits=httpx.Limits(max_connections=rate + 10),
    ) as client:
        tasks = [asyncio.create_task(one(d)) for d in domains]

        for coro in asyncio.as_completed(tasks):
            domain, result = await coro
            results[domain] = result
            done += 1
            elapsed = time.time() - t0
            speed = done / elapsed if elapsed > 0 else 0
            eta = int((len(domains) - done) / speed) if speed > 0 else 0
            if done % 200 == 0 or done == len(domains):
                print(f"  {done:,}/{len(domains):,} | {speed:.0f} dom/s | ETA {eta}s", end="\r")

    print()
    return results


def fix_shifted_rows(df: pd.DataFrame) -> pd.DataFrame:
    normal = df["email"].astype(str).str.contains("@", na=False)
    shifted = ~normal & df["city"].astype(str).str.contains("@", na=False)

    df_n = df[normal].copy()
    df_s = df[shifted].copy()
    df_s["email"] = df_s["city"]
    df_s["country"] = df_s["title"]
    df_s["city"] = df_s["state"]
    df_s["state"] = ""
    df_s["title"] = ""

    return pd.concat([df_n, df_s], ignore_index=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", type=int, default=40, help="Concurrent DoH requests")
    args = parser.parse_args()

    print(f"Читаю {INPUT}...")
    df = pd.read_csv(INPUT, low_memory=False)
    print(f"  {len(df):,} строк")

    df = fix_shifted_rows(df)
    print(f"  После фикса: {len(df):,} строк с email")

    us = df["country"].isin(["United States", "US", "USA"])
    df = df[us].copy()
    print(f"  US: {len(df):,} строк")

    df["email"] = df["email"].astype(str).str.strip().str.lower()
    df = df[df["email"].str.contains("@", na=False)].copy()
    df = df.drop_duplicates(subset=["email"]).reset_index(drop=True)
    print(f"  После дедупа по email: {len(df):,}")

    df["email_domain"] = df["email"].str.split("@").str[1]
    domains = df["email_domain"].dropna().unique().tolist()
    print(f"  Уникальных доменов: {len(domains):,}")

    print(f"\nMX чек ({args.rate} concurrent)...")
    mx_map = asyncio.run(run_mx(domains, args.rate))

    df["mx_host"] = df["email_domain"].map(lambda d: mx_map.get(d, ("", "Error"))[0])
    df["mx_provider"] = df["email_domain"].map(lambda d: mx_map.get(d, ("", "Error"))[1])
    df = df.drop(columns=["email_domain"])

    print(f"\n=== Распределение по mx_provider ===")
    vc = df["mx_provider"].value_counts()
    for provider, cnt in vc.items():
        tag = ""
        if provider == "Microsoft 365":
            tag = " <- SEPARATE"
        elif provider in GATEWAY_PROVIDERS:
            tag = " <- GATEWAY"
        elif provider in ("No MX", "Dead Domain (NXDOMAIN)"):
            tag = " <- SKIP"
        elif provider == "A-record Fallback":
            tag = " <- проверить"
        pct = 100 * cnt / len(df)
        print(f"  {provider:<35} {cnt:>6,}  ({pct:.1f}%){tag}")

    df.to_csv(OUTPUT, index=False)
    print(f"\nСохранено: {OUTPUT} ({len(df):,} строк)")

    non_ms_gw = df[
        ~df["mx_provider"].isin(
            {"Microsoft 365", "No MX", "Dead Domain (NXDOMAIN)", "Error"} | GATEWAY_PROVIDERS
        )
    ]
    print(f"Не-Microsoft / не-Gateway: {len(non_ms_gw):,} лидов")


if __name__ == "__main__":
    main()

"""
MX Provider Checker
Usage: set INPUT and OUTPUT at the top, run with: py this_file.py
Output adds two columns: mx_real, mx_provider
  mx_real     — Google / Microsoft / Microsoft (gateway) / Google (gateway) / Mimecast / Unknown / No MX
  mx_provider — direct MX name: Google / Microsoft / Hornetsecurity / Sophos / etc.
"""

import asyncio
import csv
from collections import Counter
import aiohttp

INPUT  = r"C:\Users\79818\Downloads\canada - logistic - valid_1700.csv"
OUTPUT = r"C:\Users\79818\Downloads\canada - logistic - valid_1700_mx_final.csv"

CONCURRENCY = 60

DIRECT_PATTERNS = [
    ("Google",       ["aspmx.l.google.com", "googlemail.com", "smtp.google.com",
                      "aspmx.l.google", "alt1.aspmx", "alt2.aspmx",
                      "aspmx2.googlemail", "aspmx3.googlemail"]),
    ("Microsoft",    ["mail.protection.outlook.com", "olc.protection.outlook.com",
                      "outlook.com"]),
    ("Mimecast",     ["mimecast.com"]),
    ("Proofpoint",   ["pphosted.com"]),
    ("Barracuda",    ["barracudanetworks.com"]),
    ("Zoho",         ["zoho.com", "zoho.eu", "zoho.in"]),
    ("ProtonMail",   ["protonmail.ch"]),
    ("Yahoo",        ["yahoodns.net", "yahoo.com"]),
]

GATEWAY_NAMES = {
    "hornetsecurity.com":    "Hornetsecurity",
    "ppe-hosted.com":        "Proofpoint Essentials",
    "antispameurope.com":    "Antispam Europe",
    "sophos.com":            "Sophos",
    "zerospam.ca":           "ZeroSpam",
    "trendmicro.com":        "Trend Micro",
    "mtaroutes.com":         "MTA Routes",
    "mxthunder.net":         "MX Thunder",
    "mxthunder.com":         "MX Thunder",
    "titanhq.com":           "TitanHQ",
    "esvacloud.com":         "ESVA Cloud",
    "gosecure.net":          "GoSecure",
    "siteprotect.com":       "SiteProtect",
    "mailhop.org":           "Mailhop",
    "emailservice.co":       "Email Service",
    "emailservice.io":       "Email Service",
    "emailservice.cc":       "Email Service",
    "iphmx.com":             "Cisco IronPort",
    "arsmtp.com":            "AR SMTP",
    "wtbvc.com":             "WTBVC",
    "megamailservers.com":   "Mega Mail Servers",
    "mycloudmailbox.com":    "My Cloud Mailbox",
    "bellnet.ca":            "Bell Net",
    "cloudfilter.net":       "Cloud Filter",
    "omegacloud.ca":         "Omega Cloud",
    "ncisystems.com":        "NCI Systems",
    "mailspamprotection.com": "Mail Spam Protection",
}

SPF_MS     = ["spf.protection.outlook.com", "sharepointonline.com", "onmicrosoft.com"]
SPF_GOOGLE = ["_spf.google.com", "googlemail.com"]


def classify(mx_records, txt):
    """Returns (mx_real, mx_provider)"""
    if not mx_records:
        return "No MX", "No MX"
    combined = " ".join(mx_records).lower()
    for provider, patterns in DIRECT_PATTERNS:
        if any(p in combined for p in patterns):
            return provider, provider
    first = mx_records[0].rstrip(".").split(".")
    root = ".".join(first[-2:]) if len(first) >= 2 else mx_records[0]
    gname = GATEWAY_NAMES.get(root, root)
    spf_hint = ("Microsoft" if any(p in txt for p in SPF_MS)
                else "Google" if any(p in txt for p in SPF_GOOGLE) else "")
    if spf_hint:
        mx_real = f"{spf_hint} (gateway)"
    elif gname in ("Mimecast", "Proofpoint", "Barracuda", "Proofpoint Essentials"):
        mx_real = gname
    else:
        mx_real = "Unknown"
    return mx_real, gname


def domain_from_email(email):
    email = email.strip().lower()
    return email.split("@", 1)[1] if "@" in email else ""


async def fetch(session, domain, sem):
    async with sem:
        mx, txt = [], ""
        for rtype in ("MX", "TXT"):
            for attempt in range(3):
                try:
                    url = f"https://dns.google/resolve?name={domain}&type={rtype}"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                        if r.status == 429:
                            await asyncio.sleep(attempt + 1)
                            continue
                        data = await r.json(content_type=None)
                        ans = data.get("Answer", [])
                        if rtype == "MX":
                            mx = [a["data"].split(" ", 1)[-1].rstrip(".") for a in ans if a.get("type") == 15]
                        else:
                            txt = " ".join(a["data"] for a in ans if a.get("type") == 16).lower()
                        break
                except Exception:
                    await asyncio.sleep(0.3)
        return domain, mx, txt


async def main():
    rows = []
    with open(INPUT, encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            rows.append(row)

    print(f"Rows: {len(rows)}")

    domains = list({domain_from_email(r.get("Email", "")) for r in rows if "@" in r.get("Email", "")})
    print(f"Unique domains: {len(domains)}")

    sem = asyncio.Semaphore(CONCURRENCY)
    results = {}
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=CONCURRENCY)) as session:
        tasks = {d: asyncio.create_task(fetch(session, d, sem)) for d in domains}
        done = 0
        for d, task in tasks.items():
            _, mx, txt = await task
            results[d] = classify(mx, txt)
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(domains)}", flush=True)

    new_fields = fieldnames + ["mx_real", "mx_provider"]
    for row in rows:
        d = domain_from_email(row.get("Email", ""))
        row["mx_real"], row["mx_provider"] = results.get(d, ("No email", "No email"))

    with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=new_fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved: {OUTPUT}")

    real_stats     = Counter(r["mx_real"] for r in rows)
    provider_stats = Counter(r["mx_provider"] for r in rows)

    print("\nmx_real:")
    for k, v in real_stats.most_common():
        print(f"  {k}: {v}")

    print("\nmx_provider:")
    for k, v in provider_stats.most_common():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())

"""
Icebreaker generator — parallel OpenRouter
Usage:
  py -3 run_icebreakers.py               # test batch (50 samples)
  py -3 run_icebreakers.py --limit 100   # first 100
  py -3 run_icebreakers.py --concurrency 50  # custom concurrency
"""

import asyncio
import httpx
import time
import json
import argparse
import sys
from typing import Optional

# ============================================================
# CONFIG
# ============================================================
OPENROUTER_API_KEY = "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"
MODEL              = "openai/gpt-oss-120b"
CONCURRENCY        = 100
TEMPERATURE        = 0.8
MAX_TOKENS         = 150

PROMPT_INSTRUCTIONS = (
    "You are writing a cold outreach opener for a recruitment company.\n"
    " \n"
    "Based on the company summary below, write exactly the line:\n"
    " \n\n"
    "Figured I'd reach out - I'm around [dreamICP] daily and they keep saying they [painTheySolve].\n"
    " \n"
    "Rules:\n"
    '- [dreamICP] must be a plural ICP group in casual operator language (e.g. "founders running SaaS teams", '
    '"ops directors at logistics firms", "CTOs at mid-market manufacturers") — NO corporate terms like '
    '"decision-makers" or "stakeholders"\n'
    '- [painTheySolve] must be a hiring-related complaint in founder casual tone (e.g. "been searching for months '
    'and keep seeing the same 10 CVs", "keep losing good candidates halfway through the process", "can\'t close a '
    'senior role without it dragging on forever") — infer from the company\'s ICP and industry even if not stated explicitly\n'
    "- Tone must sound like a founder texting another founder — casual, insider, not corporate\n"
    '- Use shorthand like: "burning weeks on", "pipeline\'s dry", "nobody shows up qualified", "keeps falling through"\n'
    '- NOT like: "struggle to find qualified talent", "face challenges in recruitment", "experience difficulty"\n'
    "- Output ONLY the 1 line, nothing else\n"
    " \n"
    "Company info:"
)

# ============================================================
# Test dataset (50 companies across industries)
# ============================================================
_RAW_SAMPLES = [
    ("B2B SaaS platform for e-commerce logistics and supply chain automation. Clients: online retailers 10-200 orders/day.",
     "Supply chain SaaS for e-commerce, 45 employees, $3M ARR"),
    ("Healthcare staffing agency placing travel nurses and allied health professionals in US hospitals.",
     "Medical staffing, 30 employees, 200+ hospital clients"),
    ("Cybersecurity firm providing managed threat detection and endpoint security for mid-market enterprises.",
     "Enterprise cybersecurity MDR, 60 employees, Series A"),
    ("Marketing automation platform for D2C brands, integrating email, SMS, and paid ads into one workflow.",
     "D2C marketing automation SaaS, 55 employees, $5M ARR"),
    ("Fractional CFO services and financial modeling for Series A-B tech startups.",
     "Fractional finance services for startups, 20 FTEs"),
    ("Recruiting software with AI screening for engineering roles at fast-growing tech companies.",
     "ATS and recruiting automation for tech, 35 employees"),
    ("Commercial real estate data platform providing deal comps, tenant analytics, and market reports.",
     "CRE data SaaS, 40 employees, enterprise clients"),
    ("Telemedicine platform for mental health connecting patients with licensed therapists within 24 hours.",
     "Mental health telehealth, 70 employees, 50k+ patients"),
    ("Industrial IoT company building sensor networks for predictive maintenance in manufacturing plants.",
     "Industrial IoT and predictive maintenance, 65 employees"),
    ("Freight brokerage technology platform connecting shippers with carriers through real-time load matching.",
     "Freight tech / digital brokerage, 80 employees, Series B"),
    ("Revenue operations consulting firm helping B2B SaaS companies build outbound sales motion from scratch.",
     "RevOps consulting for SaaS, 15 FTEs"),
    ("Compliance automation software for fintech companies navigating AML, KYC, and SOC2 requirements.",
     "Fintech compliance SaaS, 50 employees, $4M ARR"),
    ("Last-mile delivery platform for regional grocery chains, optimizing routes and driver dispatch.",
     "Last-mile logistics SaaS for grocers, 40 employees"),
    ("AI-powered contract review and legal ops platform for in-house legal teams at mid-market companies.",
     "LegalTech contract automation, 45 employees, Series A"),
    ("Custom software development agency specializing in fintech and healthcare applications on AWS.",
     "Nearshore dev agency, 90 engineers, US clients"),
    ("Dental practice management software with integrated billing, scheduling, and patient communication.",
     "Dental SaaS, 55 employees, 1200+ practices"),
    ("Event tech platform for hybrid and virtual corporate events, including registration, streaming, and analytics.",
     "Event management SaaS, 35 employees, SMB and enterprise"),
    ("Seed-stage venture fund investing in B2B SaaS companies in the US Midwest and Southeast.",
     "VC fund, 8 GPs, $40M AUM, active portfolio of 22 companies"),
    ("Expense management and corporate card platform for companies with distributed remote teams.",
     "Spend management fintech, 60 employees, Series A"),
    ("EHR integration middleware connecting legacy hospital systems with modern clinical apps via FHIR APIs.",
     "Healthcare interoperability platform, 30 engineers"),
    ("Staffing agency placing bilingual customer support and back-office staff for US companies.",
     "BPO staffing agency, 200+ placements/year"),
    ("Data analytics platform for QSR (quick-service restaurant) chains to track location performance and customer behavior.",
     "Restaurant analytics SaaS, 40 employees, 80+ chain clients"),
    ("HR tech platform providing compensation benchmarking and pay equity analysis for US employers.",
     "HR comp analytics SaaS, 30 employees, mid-market focus"),
    ("B2B lead generation agency using intent data and outbound sequences for enterprise software vendors.",
     "Demand gen agency, 25 FTEs, tech-sector clients"),
    ("Property management SaaS for small landlords and real estate investors managing 5-50 units.",
     "PropTech for small landlords, 35 employees, $2M ARR"),
    ("Online training and certification platform for HVAC, electricians, and skilled trades workers.",
     "Workforce training for skilled trades, 20 employees"),
    ("Growth equity firm investing in profitable bootstrapped SaaS companies with $1-5M ARR.",
     "PE/growth equity, 6 partners, 12 portfolio companies"),
    ("Procurement software for mid-market manufacturers automating PO management and supplier onboarding.",
     "Procurement SaaS for manufacturing, 45 employees"),
    ("Influencer marketing platform for CPG brands, connecting them with micro and nano creators.",
     "Influencer SaaS for CPG, 30 employees, Series A"),
    ("Subscription billing and dunning automation software for SaaS companies up to $10M MRR.",
     "Billing automation SaaS, 40 employees, $6M ARR"),
    ("Logistics intelligence platform providing carrier performance tracking and freight audit for shippers.",
     "Freight analytics SaaS, 50 employees, logistics sector"),
    ("Patient intake and digital front door solution for specialty medical practices and urgent care clinics.",
     "Healthcare patient engagement SaaS, 35 employees"),
    ("No-code internal tools builder allowing ops teams to build dashboards and workflows without engineers.",
     "No-code ops tools, 25 employees, YC alumni"),
    ("Accounts receivable automation for B2B companies, including collections, cash application, and disputes.",
     "AR automation fintech, 55 employees, Series B"),
    ("Commercial insurance marketplace helping small businesses compare and bind policies online.",
     "Insurtech marketplace, 45 employees, $3M ARR"),
    ("Fleet management and ELD compliance software for mid-size trucking companies (50-500 trucks).",
     "Fleet SaaS, 60 employees, 300+ trucking clients"),
    ("Embedded finance platform enabling SaaS companies to offer business banking and lending to their SMB customers.",
     "Embedded banking infrastructure, 70 engineers, Series B"),
    ("Manufacturing execution system (MES) for job shops and contract manufacturers doing custom parts.",
     "MES software for job shops, 40 employees"),
    ("Edtech platform for corporate L&D teams to create, distribute, and track skills training at scale.",
     "Corporate learning SaaS, 30 employees, mid-market"),
    ("Consumer lending fintech offering BNPL and installment loans through a white-label B2B2C model.",
     "BNPL fintech, 65 employees, Series A"),
    ("Specialty pharmaceutical distributor providing cold chain logistics for biotech and clinical trials.",
     "Pharma logistics and cold chain, 80 employees"),
    ("AI content operations platform for media companies automating research, drafting, and SEO optimization.",
     "AI content ops SaaS, 25 employees, media clients"),
    ("Background screening and identity verification platform for staffing agencies and gig economy platforms.",
     "HR verification SaaS, 45 employees, $4M ARR"),
    ("Construction project management software for general contractors managing $5M-$50M projects.",
     "ConTech SaaS, 50 employees, 400+ GC clients"),
    ("Digital signage and in-store experience platform for retail chains with 10-500 locations.",
     "Retail digital signage SaaS, 35 employees"),
    ("Revenue cycle management outsourcing for independent physician groups and ambulatory surgery centers.",
     "RCM services for medical practices, 120 employees"),
    ("B2B data enrichment platform providing technographic, firmographic, and contact data for sales teams.",
     "Sales intelligence data, 40 employees, Series A"),
    ("Warehouse management system built for 3PLs handling e-commerce fulfillment operations.",
     "3PL WMS SaaS, 55 employees, $5M ARR"),
    ("Climate tech startup building carbon accounting and ESG reporting tools for mid-market manufacturers.",
     "ESG SaaS for manufacturers, 20 employees, seed stage"),
    ("Independent financial advisory firm managing wealth for tech founders and executives post-liquidity.",
     "RIA for tech founders, 12 advisors, $800M AUM"),
]

TEST_COMPANIES = [
    {
        "row_number": i + 1,
        "Website Summary": summary,
        "Company Short Description": desc,
    }
    for i, (summary, desc) in enumerate(_RAW_SAMPLES)
]


# ============================================================
# Core: generate one icebreaker via OpenRouter
# ============================================================
async def generate_icebreaker(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    item: dict,
    prompt_instructions: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> dict:
    summary = (item.get("Website Summary") or "").strip()
    desc    = (item.get("Company Short Description") or "").strip()
    prompt  = prompt_instructions + "\n\n" + summary + "\n\n" + desc

    async with sem:
        try:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            icebreaker = data["choices"][0]["message"]["content"].strip()
            return {"row_number": item.get("row_number"), "Personalisation": icebreaker, "_error": None}
        except Exception as e:
            return {"row_number": item.get("row_number"), "Personalisation": "", "_error": str(e)}


# ============================================================
# Batch runner — returns list of results + timing stats
# ============================================================
async def run_batch(
    leads: list[dict],
    api_key: str = OPENROUTER_API_KEY,
    model: str = MODEL,
    concurrency: int = CONCURRENCY,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    prompt_instructions: str = PROMPT_INSTRUCTIONS,
    verbose: bool = True,
) -> dict:
    sem = asyncio.Semaphore(concurrency)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    if verbose:
        print(f"\nLeads: {len(leads)}  |  Model: {model}  |  Concurrency: {concurrency}")
        print("-" * 60)

    t_start = time.perf_counter()

    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [
            generate_icebreaker(client, sem, item, prompt_instructions, model, temperature, max_tokens)
            for item in leads
        ]
        results = await asyncio.gather(*tasks)

    t_end = time.perf_counter()
    elapsed = t_end - t_start

    errors   = [r for r in results if r["_error"]]
    success  = [r for r in results if not r["_error"]]

    stats = {
        "total":     len(leads),
        "success":   len(success),
        "errors":    len(errors),
        "elapsed_s": round(elapsed, 2),
        "leads_per_second": round(len(leads) / elapsed, 1),
        "results":   results,
    }

    if verbose:
        print(f"Done in {elapsed:.2f}s")
        print(f"Success: {len(success)}/{len(leads)}  |  Errors: {len(errors)}")
        print(f"Speed: {stats['leads_per_second']} leads/sec")
        print()

        extrapolations = [500, 1500, 2000]
        for n in extrapolations:
            est = n / stats["leads_per_second"]
            print(f"  {n:>5} leads -> ~{est:.0f}s  (~{est/60:.1f} min)")
        print()

        print("Sample output (first 5):")
        for r in success[:5]:
            row = r.get("row_number", "?")
            text = r["Personalisation"][:120]
            err = ""
            print(f"  [{row}] {text}")
        print()

        if errors:
            print(f"Errors ({len(errors)}):")
            for e in errors[:5]:
                print(f"  row {e['row_number']}: {e['_error']}")

    return stats


# ============================================================
# CLI entry point
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Generate icebreakers via OpenRouter in parallel")
    parser.add_argument("--limit",       type=int, default=50,          help="Number of leads to process (0 = all)")
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY, help="Parallel requests")
    parser.add_argument("--model",       type=str, default=MODEL,       help="OpenRouter model ID")
    parser.add_argument("--json",        action="store_true",           help="Output results as JSON")
    args = parser.parse_args()

    leads = TEST_COMPANIES
    if args.limit and args.limit < len(leads):
        leads = leads[:args.limit]

    stats = asyncio.run(
        run_batch(
            leads=leads,
            concurrency=args.concurrency,
            model=args.model,
            verbose=not args.json,
        )
    )

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

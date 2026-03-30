"""
Scale test: gpt-oss-120b with sort=throughput, concurrency 10/25/50
"""
import asyncio
import httpx
import time
import sys

sys.stdout.reconfigure(encoding="utf-8")

KEY = "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"

PROMPT_BASE = (
    "You are writing a cold outreach opener for a recruitment company.\n"
    "Write exactly one line:\n"
    "Figured I'd reach out - I'm around [dreamICP] daily and they keep saying they [painTheySolve].\n"
    "Rules: casual founder tone, specific hiring pain, output ONLY that 1 line.\n\n"
    "Company info:"
)

COMPANIES_50 = [
    ("B2B SaaS for e-commerce logistics and supply chain automation.", "Supply chain SaaS, 45 employees"),
    ("Healthcare staffing agency placing travel nurses in US hospitals.", "Medical staffing, 30 employees"),
    ("Cybersecurity firm managed threat detection for mid-market.", "MDR, 60 employees, Series A"),
    ("Marketing automation for D2C brands integrating email and SMS.", "D2C marketing SaaS, 55 employees"),
    ("Fractional CFO services for Series A-B tech startups.", "Fractional finance, 20 FTEs"),
    ("Recruiting software with AI screening for engineering roles.", "ATS, 35 employees"),
    ("Commercial real estate data platform for deal comps.", "CRE data SaaS, 40 employees"),
    ("Telemedicine platform for mental health.", "Mental health telehealth, 70 employees"),
    ("Industrial IoT for predictive maintenance in manufacturing.", "Industrial IoT, 65 employees"),
    ("Freight brokerage tech connecting shippers with carriers.", "Freight tech, 80 employees"),
    ("Revenue operations consulting for B2B SaaS companies.", "RevOps consulting, 15 FTEs"),
    ("Compliance automation for fintech AML KYC SOC2.", "Fintech compliance SaaS, 50 employees"),
    ("Last-mile delivery platform for regional grocery chains.", "Last-mile logistics SaaS, 40 employees"),
    ("AI contract review platform for in-house legal teams.", "LegalTech, 45 employees"),
    ("Custom software agency for fintech and healthcare.", "Dev agency, 90 engineers"),
    ("Dental practice management software with billing.", "Dental SaaS, 55 employees"),
    ("Event tech for hybrid corporate events.", "Event management SaaS, 35 employees"),
    ("Seed venture fund investing in B2B SaaS.", "VC fund, 8 GPs, 40M AUM"),
    ("Expense management and corporate card for remote teams.", "Spend management fintech, 60 employees"),
    ("EHR integration middleware for hospital systems.", "Healthcare interoperability, 30 engineers"),
    ("Staffing agency placing bilingual customer support.", "BPO staffing, 200 placements/year"),
    ("Data analytics for QSR chains location performance.", "Restaurant analytics SaaS, 40 employees"),
    ("HR tech for compensation benchmarking and pay equity.", "HR comp analytics, 30 employees"),
    ("B2B lead generation using intent data for enterprise vendors.", "Demand gen agency, 25 FTEs"),
    ("Property management SaaS for small landlords.", "PropTech, 35 employees"),
    ("Online training certification for HVAC electricians.", "Workforce training, 20 employees"),
    ("Growth equity investing in profitable bootstrapped SaaS.", "PE growth equity, 6 partners"),
    ("Procurement software for manufacturers automating POs.", "Procurement SaaS, 45 employees"),
    ("Influencer marketing platform for CPG brands.", "Influencer SaaS, 30 employees"),
    ("Subscription billing and dunning automation for SaaS.", "Billing automation, 40 employees"),
    ("Logistics intelligence platform for carrier performance.", "Freight analytics SaaS, 50 employees"),
    ("Patient intake solution for specialty medical practices.", "Healthcare SaaS, 35 employees"),
    ("No-code internal tools builder for ops teams.", "No-code tools, 25 employees, YC"),
    ("Accounts receivable automation for B2B companies.", "AR automation fintech, 55 employees"),
    ("Commercial insurance marketplace for small businesses.", "Insurtech marketplace, 45 employees"),
    ("Fleet management and ELD compliance for trucking.", "Fleet SaaS, 60 employees"),
    ("Embedded finance platform enabling SaaS to offer banking.", "Embedded banking, 70 engineers"),
    ("Manufacturing execution system for job shops.", "MES software, 40 employees"),
    ("Edtech platform for corporate L&D teams.", "Corporate learning SaaS, 30 employees"),
    ("Consumer lending fintech offering BNPL.", "BNPL fintech, 65 employees"),
    ("Specialty pharma cold chain logistics for biotech.", "Pharma logistics, 80 employees"),
    ("AI content operations for media companies.", "AI content ops SaaS, 25 employees"),
    ("Background screening and identity verification.", "HR verification SaaS, 45 employees"),
    ("Construction project management for general contractors.", "ConTech SaaS, 50 employees"),
    ("Digital signage platform for retail chains.", "Retail digital signage, 35 employees"),
    ("Revenue cycle management for physician groups.", "RCM services, 120 employees"),
    ("B2B data enrichment technographic firmographic.", "Sales intelligence, 40 employees"),
    ("Warehouse management system for 3PLs.", "3PL WMS SaaS, 55 employees"),
    ("Carbon accounting and ESG reporting for manufacturers.", "ESG SaaS, 20 employees, seed"),
    ("Financial advisory for tech founders post-liquidity.", "RIA, 12 advisors, 800M AUM"),
]


async def call(client, sem, idx, summary, desc):
    prompt = PROMPT_BASE + "\n\n" + summary + "\n\n" + desc
    async with sem:
        t = time.perf_counter()
        try:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={
                    "model": "openai/gpt-oss-120b",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 500,
                    "provider": {"sort": "throughput"},
                },
                timeout=90.0,
            )
            elapsed = time.perf_counter() - t
            d = r.json()
            if "choices" not in d:
                return {"ok": False, "elapsed": elapsed, "error": str(d)[:100]}
            content = d["choices"][0]["message"]["content"] or ""
            usage = d.get("usage", {})
            det = usage.get("completion_tokens_details", {})
            return {
                "ok": True,
                "idx": idx,
                "elapsed": elapsed,
                "content": content.strip(),
                "reasoning_tokens": det.get("reasoning_tokens", 0),
            }
        except Exception as e:
            return {"ok": False, "elapsed": time.perf_counter() - t, "error": str(e)}


async def bench(concurrency, n):
    sem = asyncio.Semaphore(concurrency)
    headers = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    leads = COMPANIES_50[:n]
    t_start = time.perf_counter()
    async with httpx.AsyncClient(headers=headers) as client:
        results = await asyncio.gather(*[
            call(client, sem, i, s, d) for i, (s, d) in enumerate(leads)
        ])
    elapsed = time.perf_counter() - t_start

    ok = [r for r in results if r.get("ok")]
    errors = [r for r in results if not r.get("ok")]
    throughput = n / elapsed
    avg_r = sum(r["reasoning_tokens"] for r in ok) / len(ok) if ok else 0

    print(f"\n{'='*55}")
    print(f"concurrency={concurrency} | n={n} | {elapsed:.1f}s | ok={len(ok)} err={len(errors)}")
    print(f"throughput: {throughput:.2f} leads/sec | avg_reasoning={avg_r:.0f}tok")
    for n_leads in [1500, 2000]:
        est = n_leads / throughput
        print(f"  {n_leads} leads -> ~{est:.0f}s ({est/60:.1f} min)")
    if errors:
        print(f"  Errors: {[e.get('error','?')[:60] for e in errors[:3]]}")
    if ok:
        sample = ok[0]["content"][:80].encode("ascii", errors="replace").decode("ascii")
        print(f"  Sample: {sample}")


async def main():
    print("Scale test: gpt-oss-120b with sort=throughput")
    print("Old n8n: 1500 leads = 25 min (1 lead/sec sequential)")
    print()

    await bench(concurrency=10, n=10)
    await bench(concurrency=25, n=25)
    await bench(concurrency=50, n=50)


if __name__ == "__main__":
    asyncio.run(main())

"""
Benchmark: parallel icebreaker generation
Compares gpt-oss-120b vs llama-3.3-70b on 50 leads
"""
import asyncio
import httpx
import time

KEY = "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"

PROMPT_BASE = (
    "You are writing a cold outreach opener for a recruitment company.\n"
    " \n"
    "Based on the company summary below, write exactly the line:\n"
    " \n\n"
    "Figured I'd reach out - I'm around [dreamICP] daily and they keep saying they [painTheySolve].\n"
    " \n"
    "Rules:\n"
    "- [dreamICP] must be a plural ICP group in casual operator language\n"
    "- [painTheySolve] must be a hiring-related complaint in founder casual tone\n"
    "- Tone: founder texting founder, casual, insider, not corporate\n"
    "- Use shorthand: burning weeks on, pipeline is dry, nobody shows up qualified\n"
    "- NOT: struggle to find qualified talent, face challenges, experience difficulty\n"
    "- Output ONLY the 1 line, nothing else\n"
    " \n"
    "Company info:"
)

COMPANIES = [
    ("B2B SaaS platform for e-commerce logistics and supply chain automation.", "Supply chain SaaS, 45 employees, 3M ARR"),
    ("Healthcare staffing agency placing travel nurses in US hospitals.", "Medical staffing, 30 employees"),
    ("Cybersecurity firm managed threat detection for mid-market enterprises.", "Enterprise MDR, 60 employees, Series A"),
    ("Marketing automation platform for D2C brands integrating email and SMS.", "D2C marketing SaaS, 55 employees"),
    ("Fractional CFO services for Series A-B tech startups.", "Fractional finance, 20 FTEs"),
    ("Recruiting software with AI screening for engineering roles.", "ATS and recruiting SaaS, 35 employees"),
    ("Commercial real estate data platform for deal comps and tenant analytics.", "CRE data SaaS, 40 employees"),
    ("Telemedicine platform for mental health connecting patients with therapists.", "Mental health telehealth, 70 employees"),
    ("Industrial IoT for predictive maintenance in manufacturing plants.", "Industrial IoT, 65 employees"),
    ("Freight brokerage tech connecting shippers with carriers via load matching.", "Freight tech, 80 employees"),
    ("Revenue operations consulting for B2B SaaS companies building outbound.", "RevOps consulting, 15 FTEs"),
    ("Compliance automation software for fintech AML KYC SOC2.", "Fintech compliance SaaS, 50 employees"),
    ("Last-mile delivery platform for regional grocery chains.", "Last-mile logistics SaaS, 40 employees"),
    ("AI contract review and legal ops platform for in-house legal teams.", "LegalTech contract automation, 45 employees"),
    ("Custom software development agency for fintech and healthcare on AWS.", "Nearshore dev agency, 90 engineers"),
    ("Dental practice management software with billing and scheduling.", "Dental SaaS, 55 employees, 1200 practices"),
    ("Event tech for hybrid and virtual corporate events.", "Event management SaaS, 35 employees"),
    ("Seed-stage venture fund investing in B2B SaaS Midwest Southeast.", "VC fund, 8 GPs, 40M AUM"),
    ("Expense management and corporate card for distributed remote teams.", "Spend management fintech, 60 employees"),
    ("EHR integration middleware connecting hospital systems with clinical apps.", "Healthcare interoperability, 30 engineers"),
    ("Staffing agency placing bilingual customer support for US companies.", "BPO staffing agency, 200 placements/year"),
    ("Data analytics for QSR chains to track location performance.", "Restaurant analytics SaaS, 40 employees"),
    ("HR tech platform for compensation benchmarking and pay equity analysis.", "HR comp analytics SaaS, 30 employees"),
    ("B2B lead generation agency using intent data for enterprise software vendors.", "Demand gen agency, 25 FTEs"),
    ("Property management SaaS for small landlords managing 5-50 units.", "PropTech for landlords, 35 employees"),
    ("Online training and certification for HVAC electricians skilled trades.", "Workforce training skilled trades, 20 employees"),
    ("Growth equity firm investing in profitable bootstrapped SaaS 1-5M ARR.", "PE growth equity, 6 partners, 12 portfolio"),
    ("Procurement software for mid-market manufacturers automating PO management.", "Procurement SaaS manufacturing, 45 employees"),
    ("Influencer marketing platform for CPG brands and micro creators.", "Influencer SaaS CPG, 30 employees, Series A"),
    ("Subscription billing and dunning automation for SaaS up to 10M MRR.", "Billing automation SaaS, 40 employees"),
    ("Logistics intelligence platform for carrier performance and freight audit.", "Freight analytics SaaS, 50 employees"),
    ("Patient intake solution for specialty medical practices and urgent care.", "Healthcare patient engagement SaaS, 35 employees"),
    ("No-code internal tools builder for ops teams to build dashboards.", "No-code ops tools, 25 employees, YC alumni"),
    ("Accounts receivable automation for B2B companies including collections.", "AR automation fintech, 55 employees, Series B"),
    ("Commercial insurance marketplace for small businesses to compare policies.", "Insurtech marketplace, 45 employees"),
    ("Fleet management and ELD compliance for mid-size trucking companies.", "Fleet SaaS, 60 employees, 300 trucking clients"),
    ("Embedded finance platform enabling SaaS companies to offer banking.", "Embedded banking infrastructure, 70 engineers"),
    ("Manufacturing execution system for job shops and contract manufacturers.", "MES software for job shops, 40 employees"),
    ("Edtech platform for corporate L&D teams to distribute skills training.", "Corporate learning SaaS, 30 employees"),
    ("Consumer lending fintech offering BNPL through white-label B2B2C model.", "BNPL fintech, 65 employees, Series A"),
    ("Specialty pharma distributor providing cold chain logistics for biotech.", "Pharma logistics cold chain, 80 employees"),
    ("AI content operations platform for media companies automating research.", "AI content ops SaaS, 25 employees"),
    ("Background screening and identity verification for staffing agencies.", "HR verification SaaS, 45 employees, 4M ARR"),
    ("Construction project management for general contractors 5M-50M projects.", "ConTech SaaS, 50 employees, 400 GC clients"),
    ("Digital signage platform for retail chains with 10-500 locations.", "Retail digital signage SaaS, 35 employees"),
    ("Revenue cycle management for independent physician groups and ASCs.", "RCM services medical practices, 120 employees"),
    ("B2B data enrichment platform technographic firmographic for sales teams.", "Sales intelligence data, 40 employees, Series A"),
    ("Warehouse management system built for 3PLs handling e-commerce.", "3PL WMS SaaS, 55 employees, 5M ARR"),
    ("Climate tech building carbon accounting and ESG reporting for manufacturers.", "ESG SaaS manufacturers, 20 employees, seed"),
    ("Independent financial advisory for tech founders and executives post-liquidity.", "RIA for tech founders, 12 advisors, 800M AUM"),
]


async def single_call(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                      idx: int, summary: str, desc: str,
                      model: str, extra: dict) -> dict:
    prompt = PROMPT_BASE + "\n\n" + summary + "\n\n" + desc
    async with sem:
        t = time.perf_counter()
        try:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 2000,
                    **extra,
                },
                timeout=60.0,
            )
            elapsed = time.perf_counter() - t
            d = r.json()
            if "choices" not in d:
                return {"idx": idx, "ok": False, "elapsed": elapsed, "error": str(d)}
            content = d["choices"][0]["message"]["content"]
            if content is None:
                content = ""
            return {"idx": idx, "ok": True, "elapsed": elapsed, "content": content.strip()}
        except Exception as e:
            return {"idx": idx, "ok": False, "elapsed": time.perf_counter() - t, "error": str(e)}


async def benchmark(model: str, extra: dict, label: str, concurrency: int = 50):
    sem = asyncio.Semaphore(concurrency)
    headers = {
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
    }
    t_start = time.perf_counter()
    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [
            single_call(client, sem, i, s, d, model, extra)
            for i, (s, d) in enumerate(COMPANIES)
        ]
        results = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - t_start

    ok = [r for r in results if r["ok"]]
    errors = [r for r in results if not r["ok"]]
    avg_call = sum(r["elapsed"] for r in ok) / len(ok) if ok else 0

    print(f"\n{'='*60}")
    print(f"Model: {label}")
    print(f"Leads: {len(COMPANIES)} | Concurrency: {concurrency}")
    print(f"Total time: {elapsed:.1f}s | Success: {len(ok)}/{len(COMPANIES)} | Errors: {len(errors)}")
    print(f"Avg call time: {avg_call:.2f}s | Throughput: {len(COMPANIES)/elapsed:.1f} leads/sec")
    print()
    print("Extrapolation:")
    for n in [500, 1500, 2000]:
        est = n / (len(COMPANIES) / elapsed)
        print(f"  {n:>5} leads -> ~{est:.0f}s (~{est/60:.1f} min)")
    print()
    print("Sample outputs (first 3):")
    for r in ok[:3]:
        print(f"  [{r['idx']}] {r['content'][:110]}")
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors[:3]:
            print(f"  [{e['idx']}] {e['error'][:100]}")


async def main():
    print("Running parallel benchmark: 50 leads, concurrency=50")
    print("Reference: old n8n workflow = 1500 leads in ~25 min (1 lead/sec sequential)")

    await benchmark(
        "openai/gpt-oss-120b",
        {"reasoning_effort": "low"},
        "gpt-oss-120b (reasoning_effort=low)",
        concurrency=50,
    )

    await benchmark(
        "meta-llama/llama-3.3-70b-instruct",
        {},
        "llama-3.3-70b-instruct (no reasoning)",
        concurrency=50,
    )


if __name__ == "__main__":
    asyncio.run(main())

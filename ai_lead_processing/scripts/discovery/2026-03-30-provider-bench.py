"""
Benchmark gpt-oss-120b with different provider routing strategies
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

COMPANIES = [
    ("B2B SaaS for e-commerce logistics and supply chain automation.", "Supply chain SaaS, 45 employees, 3M ARR"),
    ("Healthcare staffing agency placing travel nurses in US hospitals.", "Medical staffing, 30 employees"),
    ("Cybersecurity firm managed threat detection for mid-market.", "MDR, 60 employees, Series A"),
    ("Marketing automation for D2C brands integrating email and SMS.", "D2C marketing SaaS, 55 employees"),
    ("Fractional CFO services for Series A-B tech startups.", "Fractional finance, 20 FTEs"),
    ("Recruiting software with AI screening for engineering roles.", "ATS, 35 employees"),
    ("Commercial real estate data platform for deal comps.", "CRE data SaaS, 40 employees"),
    ("Telemedicine platform for mental health connecting patients with therapists.", "Mental health telehealth, 70 employees"),
    ("Industrial IoT for predictive maintenance in manufacturing plants.", "Industrial IoT, 65 employees"),
    ("Freight brokerage tech connecting shippers with carriers.", "Freight tech, 80 employees"),
]


async def call(client, sem, idx, summary, desc, extra_body):
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
                    **extra_body,
                },
                timeout=90.0,
            )
            elapsed = time.perf_counter() - t
            d = r.json()
            if "choices" not in d:
                return {"ok": False, "elapsed": elapsed, "error": str(d)[:150]}
            content = d["choices"][0]["message"]["content"] or ""
            usage = d.get("usage", {})
            det = usage.get("completion_tokens_details", {})
            return {
                "ok": True,
                "idx": idx,
                "elapsed": elapsed,
                "content": content.strip(),
                "reasoning_tokens": det.get("reasoning_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "upstream_cost": usage.get("cost_details", {}).get("upstream_inference_cost", 0),
            }
        except Exception as e:
            return {"ok": False, "elapsed": time.perf_counter() - t, "error": str(e)}


async def bench(extra_body, label, n=10, concurrency=10):
    sem = asyncio.Semaphore(concurrency)
    headers = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    t_start = time.perf_counter()
    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [
            call(client, sem, i, s, d, extra_body)
            for i, (s, d) in enumerate(COMPANIES[:n])
        ]
        results = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - t_start

    ok = [r for r in results if r.get("ok")]
    errors = [r for r in results if not r.get("ok")]
    avg_reasoning = sum(r["reasoning_tokens"] for r in ok) / len(ok) if ok else 0
    throughput = n / elapsed

    print(f"\n{'='*60}")
    print(f"Strategy: {label}")
    print(f"Total: {elapsed:.1f}s | ok={len(ok)}/{n} | err={len(errors)} | avg_reasoning_tok={avg_reasoning:.0f}")
    print(f"Throughput: {throughput:.2f} leads/sec")
    for n_leads in [1500, 2000]:
        est = n_leads / throughput
        print(f"  {n_leads} leads -> ~{est:.0f}s ({est/60:.1f} min)")
    print("Samples:")
    for r in ok[:3]:
        content_safe = r["content"][:90].encode("ascii", errors="replace").decode("ascii")
        print(f"  [{r['idx']}] {r['elapsed']:.1f}s | reason={r['reasoning_tokens']}tok | {content_safe}")
    if errors:
        for e in errors[:2]:
            print(f"  ERROR: {e.get('error', '?')[:100]}")


async def main():
    print("Benchmark: gpt-oss-120b provider routing strategies")
    print("10 leads, concurrency=10 each")
    print("Reference: old n8n sequential = ~1 lead/sec")

    # 1. Default routing (price-weighted = SiliconFlow, cheapest/slowest)
    await bench({}, "DEFAULT (price-weighted, cheapest provider)", n=10)

    # 2. Sort by throughput (fastest available provider)
    await bench(
        {"provider": {"sort": "throughput"}},
        "NITRO sort=throughput (fastest provider)",
        n=10,
    )

    # 3. Sort throughput + reasoning=low to minimize thinking tokens
    await bench(
        {"provider": {"sort": "throughput"}, "reasoning_effort": "low"},
        "NITRO + reasoning_effort=low",
        n=10,
    )

    # 4. Sort throughput + ignore SiliconFlow (force fastest non-default)
    await bench(
        {"provider": {"sort": "throughput", "ignore": ["SiliconFlow"]}},
        "NITRO + ignore SiliconFlow",
        n=10,
    )


if __name__ == "__main__":
    asyncio.run(main())

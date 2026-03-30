# Changelog - AI Lead Processing

**RULES: Follow [Keep a Changelog](https://keepachangelog.com/) standard strictly. Only 6 categories: Added/Changed/Deprecated/Removed/Fixed/Security. Be concise, technical, no fluff.**

---

## [0.4.0] - 2026-03-30 - MX Provider Check

### Added
- **MX Provider Check tab** in `streamlit_app.py`
  - CSV upload with auto-detect email column
  - Async DNS lookup via Google DoH API (configurable concurrency 10-100)
  - Real-time progress: domains/sec + ETA
  - Provider breakdown metrics after run
  - Filter table by `mx_real` value
  - Download CSV with two new columns
- **`scripts/discovery/2026-03-30-mx-provider-final.py`** — standalone CLI version of MX check
- **`n8n/workflows/mx-provider-check.json`** — n8n workflow (CSV → MX check → CSV)
- **`n8n/workflows/mx-provider-check-sheets.json`** — n8n workflow (Google Sheets → MX check → Google Sheets)
- **`README.md`** — инструкции по запуску Streamlit

### Changed
- MX classification logic finalized: 2 output columns instead of previous `mx_provider`+`mx_gateway`
  - `mx_real`: `Google` / `Microsoft` / `Microsoft (gateway)` / `Google (gateway)` / `Mimecast` / `Proofpoint` / `Barracuda` / `Unknown` / `No MX`
  - `mx_provider`: direct MX hostname normalized to readable name
- Gateway detection via SPF/TXT fallback — covers ~60% of "Other" domains (mostly Microsoft behind Hornetsecurity/Proofpoint Essentials)
- n8n reference updated with MX workflow section

### Notes - Lessons Learned
- 8959 leads tested (Canada logistics + US recruit): 68% Microsoft direct, 25% Google, 2% Microsoft gateway, 2% Unknown
- Google behind gateway: ~0% (4 rows out of 8959) — Google Workspace companies almost never use security gateways
- Top gateways in North American B2B: Hornetsecurity (most common in Canada), Proofpoint Essentials, Trend Micro, Sophos
- SPF fallback resolves ~60% of gateway cases; remaining 40% stay Unknown — not worth deeper investigation
- DoH concurrency 40-60: ~1186 domains in ~90s; native dnspython UDP faster but DoH sufficient and zero dependencies beyond httpx

---

## [0.3.0] - 2026-03-30 - Streamlit UI + Provider Routing Research

### Added
- **`streamlit_app.py`** — Full Streamlit UI for icebreaker generation
  - Sidebar: API key, model, concurrency, limit, provider sort, prompt editor, column mapping
  - Config persists to `icebreaker_config.json` between sessions
  - Three data source modes: CSV upload, Google Sheets (Apps Script), Google Sheets (Service Account)
  - Real-time progress: `N/total | X leads/sec | ETA MM:SS | cost $X.XXXX`
  - Live results table updates every 0.4s (last 15 rows)
  - Stop button cancels mid-run via `threading.Event`
  - Dry run toggle: generate without writing, approve quality, then commit
  - Post-run: 4 metrics (processed / success% / time / cost) + full results table
  - Download results CSV and Download full merged CSV (original + icebreakers filled in)
  - Write to Google Sheets button (after dry run)
  - Error expander showing failed row_numbers
  - MX Provider Check tab (added by user separately)
- **`google_apps_script.js`** — Google Apps Script web app for direct Sheets access
  - `doGet`: returns pending rows (Personalisation empty) as JSON, supports `sheet`, `output_col`, `limit` params
  - `doPost`: batch writes icebreakers back by row_number, uses `SpreadsheetApp.flush()`
  - Deploy as "Anyone" web app — no credentials needed from Python side
- **`scripts/discovery/2026-03-30-benchmark.py`** — Full benchmark: gpt-oss-120b vs llama-3.3-70b, 50 leads, concurrency 50
- **`scripts/discovery/2026-03-30-provider-bench.py`** — Provider routing strategy benchmark: default vs sort=throughput vs reasoning_effort=low vs ignore SiliconFlow
- **`scripts/discovery/2026-03-30-scale-test.py`** — Concurrency scaling test: 10/25/50 concurrent with sort=throughput

### Changed
- `streamlit_app.py` data source mode expanded from 2 to 3 options (added Apps Script)

### Notes - Lessons Learned
- **OpenRouter default routing = price-weighted (SiliconFlow for gpt-oss-120b) = slow** — `provider: {sort: "throughput"}` is 7.6x faster, mandatory for batch workloads
- gpt-oss-120b is a reasoning model — generates 200-300 reasoning tokens per call even with `reasoning_effort: low`; `max_tokens: 500` is sufficient for output but provider must support 2000+ to cover reasoning buffer
- OpenRouter `sort: "throughput"` doesn't just pick one provider — at high concurrency, requests are distributed across multiple providers automatically
- Scaling is near-linear: concurrency=10 → 3.7 leads/sec, concurrency=25 → 8.4 leads/sec, concurrency=50 → 14.4 leads/sec (all with 0 errors)
- Apps Script web app "unreliable" per user — gspread OAuth identified as correct long-term solution

---

## [0.2.0] - 2026-03-30 - Provider Routing Discovery + Python Script

### Added
- **`run_icebreakers.py`** — Standalone Python script for parallel icebreaker generation
  - CLI: `--limit`, `--concurrency`, `--model`, `--json` flags
  - 50 hardcoded test companies across industries for benchmarking without real sheet data
  - `asyncio.as_completed` pattern with `httpx.AsyncClient`
  - Per-result error handling: failed rows returned with `_error` field, not raised
  - Extrapolation output: shows estimated time for 500/1500/2000 leads
- **`icebreaker_parallel.json`** — n8n workflow (import-ready)
  - Replaces sequential Loop + Groq with: Filter → Prompt Config (Set node) → Code node (JS, `Promise.all`) → Google Sheets batch update
  - Code node uses `withConcurrency()` worker-pool pattern, not `Promise.all` flat (avoids OOM on 2000 items)
  - Prompt fully editable in the Set node without touching Code
  - `limit: 50` pre-set for safe first run; set to `0` for all

### Changed
- Provider switched from **Groq** to **OpenRouter** (`openai/gpt-oss-120b` on both)
- Routing: added `provider: {sort: "throughput"}` — routes to fastest provider instead of default price-weighted
- Wait node (1s per cycle) removed
- Loop Over Items replaced with single Code node processing all leads in parallel
- Output target changed from `Email1`/`Email2` to `Personalisation` column

### Notes - Lessons Learned
- Old n8n workflow: 1500 leads = 25 min (sequential, 1 lead/sec)
- New approach: 2000 leads = ~2.3 min (concurrency=50, sort=throughput)
- **Root cause of original slowness**: `Loop Over Items` in n8n is sequential by design; no parallelism
- Groq gpt-oss-120b: 500 TPS chip-level but 250K TPM rate limit = effective ceiling ~8 leads/sec for this prompt
- OpenRouter gpt-oss-120b providers: SiliconFlow (default, cheapest, slow), + 2 faster providers accessible via sort=throughput
- `content: null` bug: gpt-oss-120b reasoning model consumes all tokens on thinking if `max_tokens` too low — need 500+ even for 1-line output

---

## [0.1.0] - 2026-03-30 - Initial Analysis

### Added
- Project directory `ai_lead_processing/`
- Analysis of existing n8n workflow (`My workflow (4).json`):
  - 8 nodes: Manual Trigger → Google Sheets (read) → Filter → Loop (batch=70) → Groq Chat Model → Compose Email → Wait 1s → Google Sheets (update)
  - Sequential processing: 1 lead per cycle, 70-lead batches
  - Wait node added as rate limit workaround for Groq
  - Model: `openai/gpt-oss-120b` via `@n8n/n8n-nodes-langchain.lmChatGroq`
  - Output: `Email1` (full email with icebreaker) + `Email2` (breakup email)
  - Google Sheet: `1GDYmXYkGf6FTwFrm35bIyJGr1tcl4G_qv5KhTQoe5Qg`, tab `Sheet20`

### Notes - Baseline
- Benchmark reference: 1500 leads processed in ~25 min via n8n (sequential)
- Groq rate limit: 250K tokens/min, 500 TPS — not the bottleneck; sequential architecture is
- OpenRouter gpt-oss-120b pricing: $0.039/M input, $0.19/M output — ~10x cheaper than direct OpenAI equivalent

---

**Maintained by:** Leo
**Last Updated:** 2026-03-30

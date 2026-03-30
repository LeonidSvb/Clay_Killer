# Changelog - N8N VPS

**RULES: Follow [Keep a Changelog](https://keepachangelog.com/) standard strictly. Only 6 categories: Added/Changed/Deprecated/Removed/Fixed/Security. Be concise, technical, no fluff.**

---

## [Unreleased]

---

## [2026-03-26]

### Added
- Теги созданы через API и расставлены на все 33 воркфлоу: `PLUSVIBE`, `FATHOM`, `CAL`, `UTIL`, `OUTREACH`, `ARCHIVE`
- `reference.md` — документ с API эндпойнтами, credentials IDs, правилами построения воркфлоу, гипотезами
- Папка `n8n/` с подпапками `workflows/` и `templates/`

### Changed
- `.env` проекта `sales-calls-fathom` дополнен переменными `N8N_URL`, `N8N_API_KEY`, `VPS_HOST`

### Deprecated
- 13 воркфлоу помечены тегом `ARCHIVE`: vollna, Exmoor, shopify-abandoned, My Sub-workflow, instantly test, All Instantly Replies, PlusVibe v1 (3 шт), Outreach Report дубль, firecrawl summary, website scraper, rapid api google search

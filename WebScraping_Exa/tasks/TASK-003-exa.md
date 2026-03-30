---
id: "TASK-003"
title: "core/exa.py — Exa API wrapper (text + subpages, без summary)"
status: "planned"
priority: "P0"
labels: ["core", "exa"]
dependencies: ["TASK-001"]
created: "2026-03-30"
---

# 1) High-Level Objective

Рефакторинг существующего exa_summary.py в `core/exa.py`.
Убрать Exa summary — возвращаем только text (summary делает своя LLM).
Поддержка subpages для Pass 3 (confidence < 6).

# 2) Background / Context

Бенчмарк (реальные тесты на 100 URL):
  concurrency=50, maxAgeHours=24 → 7.6 URL/sec, 92% в кэше
  concurrency=50, maxAgeHours=-1 → быстрее но 8% пустых

Используется для:
  Pass 1b: js_heavy + blocked (subpages=0)
  Pass 3:  любые с confidence < 6 (subpages=5)

Существующий код: exa_summary.py (в корне проекта) — использовать как референс.

# 3) Assumptions & Constraints

- Constraint: maxAgeHours=24 (дефолт) — кэш + livecrawl fallback
- Constraint: НЕ запрашивать Exa summary — только text
- Constraint: concurrency=50 дефолт
- ASSUMPTION: Exa API key в .env как EXA_API_KEY

# 4) Dependencies

- .env (EXA_API_KEY)
- core/prescreener.py ScreenResult _(read-only)_
- exa_summary.py _(read-only, референс)_

# 5) Context Plan

**Beginning:**
- exa_summary.py _(read-only)_
- docs/exa_api_reference.md _(read-only)_

**End state:**
- core/exa.py

# 6) Low-Level Steps

1. **Типы (совместимы с core/scraper.py):**
   ```python
   @dataclass
   class ExaResult:
       url: str
       pages: list[PageContent]   # тот же тип что в scraper.py
       total_text: str
       total_chars: int
       ok: bool
       error: str | None
   ```
   PageContent импортировать из core.scraper.

2. **Публичный API:**
   ```python
   async def fetch_url(
       session: aiohttp.ClientSession,
       sem: asyncio.Semaphore,
       url: str,
       subpages: int = 0,
       subpage_targets: list[str] = None,
       max_age_hours: int = 24,
       text_max_chars: int = 5000,
       timeout: int = 60,
   ) -> ExaResult: ...

   async def fetch_batch(
       urls: list[str],
       concurrency: int = 50,
       subpages: int = 0,
       subpage_targets: list[str] = None,
       max_age_hours: int = 24,
   ) -> list[ExaResult]: ...
   ```

3. **Запрос к Exa API:**
   ```python
   payload = {
       "ids": [url],
       "maxAgeHours": max_age_hours,
       "text": {"maxCharacters": text_max_chars, "verbosity": "standard"},
   }
   if subpages > 0:
       payload["subpages"] = subpages
       payload["subpage_target"] = subpage_targets or DEFAULT_SUBPAGE_TARGETS
   ```
   НЕ добавлять "summary" в payload — summary делает наша LLM.

4. **Конкатенация страниц:**
   Для main page + каждой subpage:
   ```
   [PAGE: {url}]
   {text}
   ```
   Итог: total_text = все страницы с разделителями.

5. **Error handling:**
   - HTTP != 200 → ok=False, error=f"HTTP {status}"
   - Timeout → ok=False, error="timeout"
   - Пустой text (< 100 chars) → ok=False, error="empty_response"

6. **CLI:**
   ```
   py core/exa.py --input file.csv --col company_website --limit 10 --subpages 3
   ```
   Выводит: url | chars | pages | ok/err

# 8) Acceptance Criteria

- `from core.exa import fetch_batch` работает
- На 10 URL возвращает текст без Exa summary (только raw text)
- subpages=3 возвращает PageContent для каждой найденной страницы
- ok=False для мёртвых URL без crash
- ExaResult.pages совместим с scraper.ScrapeResult.pages (один тип PageContent)

# 9) Testing Strategy

- 10 URL: fetch без subpages → замерить chars и время
- 5 URL: fetch с subpages=3 → проверить что subpages найдены
- 3 URL заведомо мёртвых → убедиться ok=False

---
id: "TASK-005"
title: "pipeline.py — CLI оркестратор: prescreener + scraper + exa + llm"
status: "planned"
priority: "P1"
labels: ["pipeline", "cli", "orchestrator"]
dependencies: ["TASK-001", "TASK-002", "TASK-003", "TASK-004"]
created: "2026-03-30"
---

# 1) High-Level Objective

Написать `pipeline.py` — CLI entry point который соединяет все core/ модули.
Три режима: hybrid (дефолт), exa-only, scraper-only.
Input: CSV. Output: CSV с новыми колонками из LLM.

# 2) Background / Context

Архитектура passes:
  Pass 0: prescreener → классификация (только в hybrid режиме)
  Pass 1a: scraper → html_light (только в hybrid)
  Pass 1b: exa → js_heavy + blocked (hybrid) или все URL (exa-only)
  Pass 2: llm → все живые сайты
  Pass 3: exa subpages + llm повтор → confidence < threshold

# 3) Assumptions & Constraints

- Constraint: CSV in → CSV out (никакого Google Sheets write-back)
- Constraint: оригинальные колонки CSV сохраняются as-is
- Constraint: если output колонка уже существует → добавить суффикс _v2
  (или --overwrite флаг)
- ASSUMPTION: URL колонка авто-детектится или задаётся через --col

# 4) Dependencies

- core/prescreener.py (TASK-001)
- core/scraper.py    (TASK-002)
- core/exa.py        (TASK-003)
- core/llm.py        (TASK-004)
- .env

# 5) Context Plan

**Beginning:**
- core/*.py (все модули)
- docs/PRD.txt _(read-only)_

**End state:**
- pipeline.py

# 6) Low-Level Steps

1. **CLI аргументы:**
   ```
   py pipeline.py \
     --input  leads.csv \
     --output leads_enriched.csv \      # дефолт: input_enriched.csv
     --col    company_website \          # авто-детект если не задан
     --limit  100 \                      # 0 = все
     --mode   hybrid \                   # hybrid | exa-only | scraper-only
     --prompt company_full \             # имя промпта из prompts/
     --cols   summary,icp_fit,geography \ # какие колонки сохранить (дефолт: все)
     --overwrite \                       # перезаписать существующие колонки
     --confidence-threshold 6 \          # ниже → Pass 3
     --subpages 5                        # для Pass 3
   ```

2. **Авто-детект URL колонки:**
   ```python
   URL_KEYWORDS = ["website", "url", "site", "domain", "web", "link"]
   # сначала по имени колонки, потом по содержимому (есть ли . без пробелов)
   ```

3. **Основной flow (hybrid режим):**
   ```python
   # Pass 0
   screen_results = await screen_batch(urls, concurrency=100)
   html_urls    = [r.url for r in screen_results if r.site_class == "html_light"]
   exa_urls     = [r.url for r in screen_results if r.site_class in ("js_heavy","blocked")]
   dead_urls    = [r.url for r in screen_results if r.site_class == "dead"]

   # Pass 1a + 1b параллельно
   scrape_task = scrape_batch(html_urls, concurrency=50)
   exa_task    = fetch_batch(exa_urls, concurrency=50)
   scrape_results, exa_results = await asyncio.gather(scrape_task, exa_task)

   # объединить в один список items = [{"url": ..., "text": ...}, ...]
   # Pass 2
   llm_results = await extract_batch(items, prompt_name=args.prompt)

   # Pass 3 — только low confidence
   retry_items = [r for r in llm_results if r.confidence < args.confidence_threshold]
   if retry_items:
       retry_exa = await fetch_batch([r.url for r in retry_items], subpages=args.subpages)
       retry_llm = await extract_batch(retry_exa_items, prompt_name=args.prompt)
       # merge: заменить low-confidence результаты на retry результаты
   ```

4. **exa-only режим:**
   - Пропустить Pass 0 и Pass 1a
   - Все URL сразу в fetch_batch

5. **scraper-only режим:**
   - Пропустить Pass 0 и Exa
   - Все URL в scrape_batch
   - Если ok=False → пометить как failed (не делать Exa fallback)

6. **Merge результатов в DataFrame:**
   ```python
   for result in llm_results:
       for key, value in result.data.items():
           if key in selected_cols:  # --cols фильтр
               df.at[idx, key] = value
   ```
   Если колонка уже существует и нет --overwrite → добавить _v2

7. **Консольный вывод во время работы:**
   ```
   [Pass 0] Screening 535 URLs...
     html_light: 287 (54%) | js_heavy: 156 (29%) | blocked: 62 (12%) | dead: 30 (6%)
   [Pass 1] Fetching content...
     Scraper: 287 URLs | Exa: 218 URLs
   [Pass 2] LLM extraction... 412/505 | 6.2/sec | ETA 1:32
   [Pass 3] Retrying 67 low-confidence URLs with subpages...
   Done: 489/535 | 30 dead | 16 errors | 89.1s total
   Saved to leads_enriched.csv
   ```

8. **Итоговая статистика в конце:**
   ```
   Mode:      hybrid
   Prompt:    company_full
   Total:     535 leads
   Processed: 505 (30 dead skipped)
   Success:   489 (96.8%)
   Pass 3:    67 retried, 54 improved
   Time:      89.1s (5.7 leads/sec)
   Exa pages: 218 ($0.22) + 335 subpages ($0.34)
   LLM cost:  ~$0.09
   Total cost: ~$0.65
   ```

# 8) Acceptance Criteria

- `py pipeline.py --input test.csv --limit 20 --mode hybrid` завершается без ошибок
- output CSV содержит все оригинальные колонки + новые из LLM
- `--mode exa-only` работает без prescreener
- dead URLs получают пустые LLM колонки (не crash)
- `--cols summary,icp_fit` сохраняет только эти две колонки из LLM output

# 9) Testing Strategy

- 20 URL, hybrid режим → проверить распределение классов
- 20 URL, exa-only → сравнить скорость и качество с hybrid
- 5 URL заведомо dead → убедиться что pipeline завершается
- Проверить что итоговый CSV читается в pandas без ошибок

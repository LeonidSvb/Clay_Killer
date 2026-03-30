---
id: "TASK-000"
title: "Backlog — мелкие недоделки и улучшения"
status: "open"
priority: "P2"
labels: ["backlog", "polish"]
created: "2026-03-31"
updated: "2026-03-31"
---

# Мелкие недоделки (делать по ходу или перед релизом)

## pipeline.py

- [ ] **Ретрай failed Exa URLs** — сейчас `exa_status=empty_results` просто пропускается.
      Добавить `--retry-failed` флаг: взять строки где `exa_status != ok` → повторить с другим
      max_age_hours (например 72h вместо 24h) или без subpages

- [ ] **Прогресс Pass 3** — добавить лейбл "[Pass 3 Exa]" / "[Pass 3 LLM]"

- [ ] **--overwrite по умолчанию** — при повторном запуске колонки получают суффикс `_llm`.
      Добавить `--overwrite` как дефолт когда колонки LLM уже существуют (спрашивать или авто)

- [ ] **Логирование в файл** — добавить `--log output.log` чтобы весь stdout писался в файл
      параллельно с выводом на экран

## prompts/

- [ ] **Реорганизация папок** — разложить по `prompts/enrichment/` и `prompts/extraction/`
      согласно TASK-006. Сейчас всё в корне `prompts/`

- [ ] **icebreaker.txt** — вынести захардкоженный промпт из `ai_lead_processing/streamlit_app.py`
      в `prompts/enrichment/icebreaker.txt`

- [ ] **relevant_observation.txt** — промпт из SSM библиотеки ещё не добавлен
      (Variable 3: наблюдение о компании для email opener)

## core/llm.py

- [ ] **cost_usd в LLMResult** — добавить поле `cost_usd` из `usage.cost` в OpenRouter ответе.
      Нужно для Run Summary stats (показывать стоимость прогона в $).
      OpenRouter возвращает это поле когда `usage` есть в ответе.

- [ ] **Retry на HTTP 429** — если OpenRouter возвращает 429 (rate limit) → подождать 2s и retry
      один раз. Сейчас это просто error

- [ ] **Стоимость в результате** — добавить в LLMResult поле `cost_usd` из `usage.cost`
      если OpenRouter его возвращает

## core/exa.py

- [ ] **max_age_hours как параметр CLI** — в `fetch_batch()` уже есть, но в CLI не пробрасывается
      через pipeline. Добавить `--max-age-hours` в pipeline.py

## Качество данных

- [ ] **Benchmark: homepage vs deep** — чёткая таблица когда что использовать:
      массовый прогон → homepage | финальный энричмент топ-лидов → deep

---

# Post-MVP фичи (Streamlit)

## Email validation enrichments

Атомарные enrichments для проверки email. Каждый — отдельный тип в панели "API Call".

- [ ] **Mailco validation** — input: email колонка → output: `mailco_status` (valid/invalid/catch-all/unknown)
      Дешёвый, хорошо покрывает ~60% базы

- [ ] **Million Verifier (через Epify)** — input: email колонка → output: `mv_status`
      Для оставшихся после Mailco

- [ ] **Catch-all domain checker** — input: email/domain → output: `catchall_status`
      Для доменов где другие валидаторы говорят catch-all

- [ ] **Email waterfall** — объединение трёх выше через Waterfall column:
      `email_verified` = первый "valid" из mailco → mv → catchall
      Итого: 60% + 20% + 10% = ~90% покрытие из трёх источников

## Waterfall column

- [ ] **Waterfall enrichment** — пользователь выбирает [col_A, col_B, col_C] →
      финальная колонка = первое непустое значение.
      Usecase: email из трёх источников, website из трёх источников.

## Boolean aggregation column

- [ ] **Boolean aggregation** — объединение true/false колонок в решение:
      пользователь выбирает колонки + оператор (AND / OR).
      Пример: `tam_ok AND ships_us AND is_b2b → qualified`.
      Каждая колонка заполнена на 20-40%, пересечение — финальный ICP список.
      Usecase: 5 отдельных LLM enrichments (каждый проверяет один критерий) →
      объединяешь в `qualified` без нового LLM вызова.

## Workflow presets (saved chains)

- [ ] **Saved workflow** — сохранённая цепочка enrichments как пресет:
      пример "Email verification" = Mailco → MV → Catchall → Waterfall.
      Запускается одной кнопкой на любом CSV.
      pipeline.py = пример такого пресета для CLI.

---

# Deep mode — архитектура (требует исследования)

Текущий подход: все страницы Exa → один текст → один LLM вызов → summary + scoring.
Проблема: при 5 subpages summary может терять информацию с отдельных страниц.

Три варианта:

- [ ] **Вариант A — Page-by-page facts extraction**
      Каждая страница → LLM извлекает сухие факты → финальный LLM объединяет
      Плюс: ни одна страница не теряется
      Минус: N+1 LLM вызовов, дороже

- [ ] **Вариант B — Весь текст в контекст (текущий, без лимитов)**
      GPT-OSS-120b контекст 128k → 75k chars входит (5 subпages × 15k chars)
      max_tokens и max_llm_chars убраны — тестируем качество
      Проверить: confidence avg на 100 deep лидах без каких-либо лимитов

- [ ] **Вариант C — Per-page summary → финальный синтез**
      Каждая страница → короткий summary (3-5 предложений)
      Все mini-summaries → финальный LLM синтезирует
      Плюс: компактный финальный контекст, нет потерь
      Минус: дороже варианта B, дешевле варианта A

      Рекомендация: сначала тестировать Вариант B. Если confidence низкий — Вариант C.

---

# Низкий приоритет / может не понадобиться

- [ ] **TASK-002 scraper.py** — кастомный scraper для html_light сайтов (~8% аудитории)

- [ ] **Дедупликация по URL** — один URL встречается несколько раз → обработать один раз

- [ ] **--dry-run** — прогнать без LLM, только Exa, показать статистику текста

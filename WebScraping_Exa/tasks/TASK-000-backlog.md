---
id: "TASK-000"
title: "Backlog — мелкие недоделки и улучшения"
status: "open"
priority: "P2"
labels: ["backlog", "polish"]
created: "2026-03-31"
---

# Мелкие недоделки (делать по ходу или перед релизом)

## pipeline.py

- [ ] **Ретрай failed Exa URLs** — сейчас `exa_status=empty_results` просто пропускается.
      Добавить `--retry-failed` флаг: взять строки где `exa_status != ok` → повторить с другим
      max_age_hours (например 72h вместо 24h) или без subpages

- [ ] **max_tokens в LLM** — сейчас 1500 для всех промптов. `company_deep` требует больше
      (summary 2000-3000 chars). Добавить в `extract_batch()` параметр `max_tokens`
      и в pipeline пробрасывать: deep=2500, обычный=1500

- [ ] **Прогресс Pass 3** — сейчас Pass 3 показывает два прогресса (Exa + LLM) без разметки.
      Добавить лейбл "[Pass 3 Exa]" / "[Pass 3 LLM]"

- [ ] **--overwrite по умолчанию** — сейчас при повторном запуске колонки получают суффикс `_llm`.
      Добавить `--overwrite` как дефолт когда колонки LLM уже существуют (спрашивать или авто)

- [ ] **Логирование в файл** — добавить `--log output.log` чтобы весь stdout писался в файл
      параллельно с выводом на экран

## prompts/

- [ ] **Перенести промпты по папкам** — разложить по `prompts/enrichment/` и `prompts/extraction/`
      согласно TASK-006. Сейчас всё в корне `prompts/`

- [ ] **icebreaker.txt** — вынести захардкоженный промпт из `ai_lead_processing/streamlit_app.py`
      в `prompts/enrichment/icebreaker.txt`

- [ ] **relevant_observation.txt** — промпт из SSM библиотеки ещё не добавлен
      (Variable 3: наблюдение о компании для email opener)

## core/llm.py

- [ ] **max_tokens параметр** — сейчас DEFAULT_MAX_TOKENS=1500 хардкод. Пробросить в
      `extract()` и `extract_batch()` чтобы pipeline мог передавать разные значения

- [ ] **Retry на HTTP 429** — если OpenRouter возвращает 429 (rate limit) → подождать 2s и retry
      один раз. Сейчас это просто error

- [ ] **Стоимость в результате** — добавить в LLMResult поле `cost_usd` из `usage.cost`
      если OpenRouter его возвращает (как в ai_lead_processing)

## core/exa.py

- [ ] **max_age_hours как параметр CLI** — в `fetch_batch()` уже есть, но в CLI не пробрасывается
      через pipeline. Добавить `--max-age-hours` в pipeline.py

## Качество данных

- [ ] **Тест: deep с max_llm_chars=8000** — проверить что confidence avg вернётся к 7.5+
      на 100 канадских лидах (сейчас без лимита было 5.5)

- [ ] **Benchmark: homepage vs deep** — чёткая таблица когда что использовать:
      массовый прогон → homepage | финальный энричмент топ-лидов → deep

## Будущие фичи (не срочно)

- [ ] **TASK-002 scraper.py** — кастомный scraper для html_light сайтов (сейчас ~8% аудитории,
      низкий приоритет)

- [ ] **Дедупликация по URL** — если один URL встречается в CSV несколько раз → обработать
      один раз, скопировать результат во все строки

- [ ] **--dry-run** — прогнать без LLM, только Exa, показать статистику текста

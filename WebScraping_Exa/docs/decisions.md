# Architecture Decisions

Lightweight ADR — зачем так, а не иначе. Только non-obvious решения.

---

## ADR-001 — OpenRouter: provider.sort=throughput обязателен

**Date**: 2026-03-30
**Status**: Accepted

**Решение**: Каждый запрос к OpenRouter содержит `"provider": {"sort": "throughput"}`.

**Почему**: Без этого OpenRouter роутит на дешёвый/медленный провайдер.
Разница: 7x медленнее без этого флага на gpt-oss-120b.
50 запросов: ~8s с флагом vs ~60s без.

**Где**: `core/llm.py` → `extract()` → payload.

---

## ADR-002 — max_llm_chars убран, доверяем контексту модели

**Date**: 2026-03-31
**Status**: Accepted (supersedes первоначальное решение от 2026-03-30)

**Решение**: Параметр `--max-llm-chars` удалён. Весь текст от Exa идёт в LLM без обрезки.

**Почему пересмотрели**: Confidence drop с 7.5 до 5.5 в deep mode был вызван не размером текста,
а max_tokens=1500 (ADR-007) — JSON ответ обрезался на полуслове.
GPT-OSS-120b имеет контекст 128k, 75k chars от 5 subpages это ~18k токенов — без проблем.
Обрезка текста — это хак, который прятал симптом (truncated JSON), а не решал причину.

**Что делать вместо обрезки**: улучшать промпт чтобы модель правильно приоритизировала
информацию из большого контекста. Если качество всё ещё низкое — исследовать варианты
page-by-page extraction (см. TASK-000 backlog → Deep mode архитектура).

**Где**: `pipeline.py` — `args.max_llm_chars` удалён везде.

---

## ADR-003 — maxAgeHours=24 в Exa обязателен

**Date**: 2026-03-30
**Status**: Accepted

**Решение**: Все запросы к Exa /contents идут с `maxAgeHours=24`.

**Почему**: Exa кэширует страницы. 92% B2B сайтов уже в кэше при 24h окне.
Без этого параметра Exa может использовать устаревший кэш или вообще не возвращать результат.
С параметром: avg latency ~0.8s/URL. Без: до 8-15s (livecrawl).

**Где**: `core/exa.py` → `fetch_url()` → payload.

---

## ADR-004 — {{column_name}} двойные скобки в промптах Streamlit

**Date**: 2026-03-31
**Status**: Accepted

**Решение**: В Streamlit-промптах переменные пишутся как `{{Company Name}}` (двойные фигурные скобки).
Подстановка: `filled = filled.replace("{{" + col + "}}", str(row[col]))`.

**Почему**: CLI-промпты используют `{text}` (одинарные) и `str.format(text=text)`.
Если использовать одинарные скобки в multi-column промптах — конфликт с Python format():
`"Company: {Company Name}"` → `KeyError: 'Company Name'`.
Двойные скобки не конфликтуют ни с format(), ни с f-strings.

**Альтернативы**:
- Jinja2 `{{ var }}` — лишняя зависимость, избыточно
- `%column_name%` — нестандартно, пользователь не поймёт

**Где**: `app/components/prompt_editor.py` + `app/enrichments/llm.py`.

---

## ADR-005 — app/enrichments/ адаптер для Streamlit

**Date**: 2026-03-31
**Status**: Accepted

**Решение**: `core/` не импортирует Streamlit. `app/enrichments/` — тонкий адаптер-слой.
Адаптер запускает core/ через `threading.Thread + queue.Queue`.

**Почему**: Streamlit не поддерживает `asyncio.run()` в основном потоке.
`core/exa.py` и `core/llm.py` — чистые async функции.
Адаптер запускает их в отдельном thread с `asyncio.run()` внутри, пробрасывает прогресс через queue.

**Следствия**:
- core/ можно запускать в CLI, Streamlit, FastAPI — без изменений
- Stop работает через `threading.Event` → worker проверяет после каждого item

**Где**: `app/enrichments/llm.py`, `app/enrichments/scraping.py`, `app/enrichments/mx.py`.

---

## ADR-006 — Clay-style workspace вместо feature-tabs

**Date**: 2026-03-31
**Status**: Accepted

**Решение**: Один Table tab + боковая панель enrichment runner. Нет отдельных табов под LLM/Scraping/MX.

**Почему**: Feature-tabs создают friction — нужно переходить между табами чтобы настроить и запустить.
Clay-style: выделил колонки в таблице → открыл панель → выбрал тип → запустил → результат рядом с данными.
История enrichment не нужна — только save/discard после каждого рана.

**Альтернативы**:
- 3 таба (LLM / Scraping / MX) — дублирует конфиг в каждом табе, нет связи с таблицей
- Sidebar всегда видна — занимает место когда не нужна

---

## ADR-007 — max_tokens убран из LLM запросов

**Date**: 2026-03-31
**Status**: Accepted (supersedes первоначальное решение от 2026-03-30)

**Решение**: `max_tokens` не передаётся в payload. Модель сама определяет длину ответа.

**Почему пересмотрели**: Изначально стояло 800 токенов → JSON обрезался → confidence=0.
Подняли до 1500 — стало лучше, но company_deep промпт всё ещё может обрезаться.
Модели дешёвые (GPT-OSS-120b), качество важнее экономии токенов.
Убрать лимит полностью — правильное решение, нет смысла хардкодить компромисс.

**История**: 800 → 1500 → убрали совсем.

**Где**: `core/llm.py` — `DEFAULT_MAX_TOKENS` константа и `max_tokens` из payload удалены.

---

## ADR-008 — exa_status + exa_chars колонки в output

**Date**: 2026-03-30
**Status**: Accepted

**Решение**: pipeline.py всегда пишет `exa_status` и `exa_chars` в output CSV.

**Почему**: Без них непонятно почему 23% строк имели пустой summary.
Оказалось — Exa не пробился (empty_results, timeout, HTTP 403).
Эти колонки позволяют: фильтровать failed URLs, делать retry, видеть coverage.

**Статусы**: `ok` | `empty_results` | `empty_text` | `timeout` | `HTTP 4xx` | `error`.

**Где**: `pipeline.py` → `exa_status_map` → write после Pass 1.

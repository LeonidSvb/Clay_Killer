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

## ADR-002 — max_llm_chars отдельно от max_chars (Exa fetch)

**Date**: 2026-03-30
**Status**: Accepted

**Решение**: `--max-llm-chars` — отдельный параметр, по умолчанию 8000 в deep mode.

**Почему**: В deep mode Exa отдаёт 15000 chars/page × 5 subpages = до 75000 chars.
Когда всё это идёт в LLM — confidence avg падает с 7.5 до 5.5.
LLM теряется в большом тексте, выдаёт неуверенные оценки.
Решение: обрезать текст перед LLM независимо от размера Exa fetch.

**Альтернативы**:
- Уменьшить max_chars в Exa — теряем качество скрапинга
- Уменьшить subpages — теряем покрытие

**Где**: `pipeline.py` → `args.max_llm_chars`, применяется перед `items_for_llm.append()`.

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

## ADR-007 — max_tokens=1500 для всех LLM запросов

**Date**: 2026-03-30
**Status**: Accepted

**Решение**: `DEFAULT_MAX_TOKENS = 1500` в `core/llm.py`.

**Почему**: При 800 токенах (прежнее значение) JSON ответ обрезался на середине.
`parse_json_response()` не мог распарсить → fallback `{"raw": ..., "confidence": 0}`.
Все строки получали confidence=0, Pass 3 retry запускался на 100% строк.

**Известное ограничение**: `company_deep` промпт нужно ~2500 токенов для полного summary.
Это в TASK-000 backlog как улучшение (max_tokens per prompt).

**Где**: `core/llm.py` → `DEFAULT_MAX_TOKENS`.

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

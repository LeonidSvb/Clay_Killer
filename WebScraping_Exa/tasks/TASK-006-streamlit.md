---
id: "TASK-006"
title: "app/ — Streamlit UI, Clay-style enrichment workspace"
status: "ready"
priority: "P1"
labels: ["ui", "streamlit", "architecture"]
dependencies: ["TASK-004", "TASK-005"]
created: "2026-03-30"
updated: "2026-03-31"
---

# 1) Концепция

Clay-style workspace: одна таблица, библиотека enrichments, каждый enrichment = input columns + config + output columns.
Без отдельных feature-табов. Всё в одном месте.

Запуск: `streamlit run app/main.py`

---

# 2) Структура файлов

```
WebScraping_Exa/
  app/
    main.py                     <- точка входа, st.tabs, shared state
    pages/
      table.py                  <- Tab 1: таблица + file browser + фильтры
      settings.py               <- Tab 2: API keys + рабочая папка + prompt manager
    components/
      enrichment_panel.py       <- боковая панель (универсальная для всех типов)
      prompt_editor.py          <- dropdown + edit + preview + column chips
      column_selector.py        <- выбор колонок из df (input + output)
      file_browser.py           <- список CSV из рабочей папки
    enrichments/                <- АДАПТЕР-СЛОЙ: Streamlit <-> core/
      llm.py                    <- обёртка extract_batch() для Streamlit
      scraping.py               <- обёртка fetch_batch() + extract_batch() для Streamlit
      mx.py                     <- MX check для Streamlit
  prompts/
    enrichment/                 <- промпты для LLM enrichment (company_full, icp_filter...)
    extraction/                 <- промпты для web scraping + extraction (company_deep...)
```

### Почему enrichments/ адаптер-слой

`core/` содержит чистые async функции без каких-либо зависимостей от Streamlit.
`app/enrichments/` — тонкие обёртки, которые:
- запускают core/ через `threading.Thread + queue.Queue` (Streamlit не поддерживает asyncio напрямую)
- пробрасывают прогресс в очередь для live-обновления UI
- принимают параметры в виде простых dict (сериализуемые, удобные для session_state)

Это означает: `core/exa.py`, `core/llm.py`, `pipeline.py` полностью независимы от Streamlit.
Их можно запускать в CLI, в Streamlit, и в будущем в FastAPI — без изменений в core/.

### Файлы которые НЕ копируются в app/

- `exa_summary.py` — прототип, заменён pipeline.py + core/. Перенести в `archive/exa_summary.py`.
- `ai_lead_processing/streamlit_app.py` — отдельный проект, не копируется.
  Используется только как reference для двух паттернов:
  1. progress через threading.Thread + queue.Queue (описан в секции 9)
  2. MX check логика → уже в core/mx.py (или будет там)

---

# 3) Два таба

```
[ Table ]   [ Settings ]
```

Всё остальное — в боковой панели (enrichment runner).

---

# 4) Tab 1 — Table

## File browser (верх страницы)

Список CSV файлов из рабочей папки (задаётся в Settings):
```
leads_canada_1700.csv       2026-03-31  1702 rows  [Open]
us_enriched_500.csv         2026-03-31   500 rows  [Open]
canada_logistic_deep.csv    2026-03-31   100 rows  [Open]
[+ Upload CSV]   [Refresh]
```
- Сканирует папку через `Path(folder).glob("*.csv")`
- Новые файлы появляются после Refresh (или авто через `st.rerun`)
- После enrichment сохраняет в ту же папку автоматически

## Таблица

```
leads_canada.csv | 1702 rows | 19 cols        [Download]  [Columns v]  [Filter v]

Company Name    | Website      | icp_fit  | confidence  | summary      | ...
Sotech Nitram   | sotech...    | 8        | 9           | Canadian...  |
Service JR      | service...   | 7        | 8           | Quebec...    |
```

- `[Columns v]` — multiselect какие колонки показывать
- `[Filter v]` — фильтры: confidence >= N, icp_fit >= N, любая колонка
- Новые колонки после enrichment подсвечиваются желтым до Save/Discard
- `st.dataframe` с `hide_index=True`
- Кликнуть заголовок колонки → добавляется в Input enrichment (через session_state)

## Run Enrichment

```
[ + Run Enrichment ]   <- кнопка, открывает боковую панель
```

---

# 5) Enrichment Panel (боковая панель)

Универсальная структура для всех типов:

```
+- Enrichment ---------------------------------------------------+
|                                                                |
|  Type:  [ LLM Extraction  v ]                                  |
|         [ Website Scraping ]                                   |
|         [ MX Check         ]                                   |
|                                                                |
|  -- [1] INPUT -------------------------------------------------|
|  Columns going into context:                                   |
|  (кликни на заголовок колонки в таблице чтобы добавить)        |
|  Selected: [Website Summary x] [Company Name x]               |
|                                                                |
|  -- [2] CONFIG (зависит от type) -----------------------------|
|  LLM:      prompt selector + model + concurrency              |
|  Scraping: mode + subpages + deep toggle                       |
|  MX:       concurrency                                         |
|                                                                |
|  -- [3] RUN ---------------------------------------------------|
|  Rows: (o) Preview 10  ( ) All  ( ) Filtered  [    ]          |
|  [ Run ]  [ Stop ]                                            |
|  progress bar + status line                                    |
|                                                                |
|  -- [4] OUTPUT (после завершения) -----------------------------|
|  Preview: 10 строк результатов                                  |
|  Choose columns to save:                                       |
|  [x] summary    -> rename: [summary              ]            |
|  [x] icp_fit    -> rename: [icp_fit              ]            |
|  [ ] services   (skip)                                         |
|  [ Save to table ]  [ Discard ]                               |
+----------------------------------------------------------------+
```

---

# 6) Система переменных в промптах: {{column_name}}

## Два разных паттерна

### Текущий CLI-паттерн (pipeline.py)
В pipeline.py промпты используют `{text}` — один текст из Exa.
`build_messages()` делает `user_template.format(text=text)`.

### Новый Streamlit-паттерн (multi-column)
В Streamlit пользователь выбирает несколько input columns.
Промпт пишется с `{{Company Name}}`, `{{Website Summary}}` и т.д.

При запуске enrichment:
```python
# row — одна строка df
filled = prompt_template
for col in input_columns:
    filled = filled.replace("{{" + col + "}}", str(row.get(col, "")))
```

Фигурные скобки `{{}}` (двойные) используются вместо `{}` чтобы не конфликтовать
с Python string.format() внутри кода.

## Prompt Editor — детали реализации

```
Prompt: [ company_full  v ]  [Edit]  [+ New]  [Delete]

+- Prompt text -------------------------------------------------+
| Analyse the company below and extract profile.                |
|                                                               |
| Company: {{Company Name}}                                     |
| Website summary: {{Website Summary}}                          |
|                                                               |
| Return JSON: { "summary": ..., "icp_fit": ... }              |
+---------------------------------------------------------------+

Available columns (click to insert at cursor):
[Company Name] [Website] [Website Summary] [Industry] [...]

Preview (row 1):
+--------------------------------------------------------------+
| Analyse the company below and extract profile.               |
| Company: Sotech Nitram Inc.                                  |
| Website summary: Canadian logistics provider since 1981...   |
+--------------------------------------------------------------+

[Save prompt]  (сохраняет в prompts/enrichment/company_full.txt)
```

**Column chips реализация:**
- Каждый chip — это `st.button(col_name)`
- При клике: `st.session_state.prompt_insert = "{{" + col_name + "}}"`
- JavaScript через `st.components.v1.html` вставляет текст в textarea
  (или через `st_ace` editor component если нативно не работает)

**Preview:**
- Берёт первую строку `st.session_state.df`
- Применяет замену `{{col}}` → реальное значение
- Показывает итоговый текст промпта как `st.code()`

**Save:**
- Перезаписывает файл в `prompts/enrichment/name.txt`
- Новые промпты в `prompts/enrichment/` автоматически доступны в dropdown

**Delete:**
- Confirm: текстовый input "введи 'delete' для подтверждения"

---

# 7) app/enrichments/ — адаптер-слой

## enrichments/llm.py

```python
# Интерфейс для Streamlit enrichment_panel.py
def run_llm_enrichment(
    df: pd.DataFrame,
    input_columns: list[str],     # колонки которые идут в промпт
    prompt_name: str,
    row_indices: list[int],       # какие строки обрабатывать
    concurrency: int,
    progress_queue: queue.Queue,  # {"done": N, "total": N, "ok": N, "errors": N}
    stop_event: threading.Event,
    api_key: str = "",
) -> list[dict]:                  # результаты: [{"url": ..., "data": {...}}, ...]
```

Внутри запускает `asyncio.run(extract_batch(...))` в отдельном thread.
Заполняет `progress_queue` по мере выполнения.

## enrichments/scraping.py

```python
def run_scraping_enrichment(
    df: pd.DataFrame,
    url_column: str,
    prompt_name: str,
    row_indices: list[int],
    mode: str,                    # "exa-only" | "hybrid" | "html-only"
    subpages: int,
    max_chars: int,
    max_llm_chars: int,
    concurrency: int,
    progress_queue: queue.Queue,  # два прогресса: pass1_queue + pass2_queue
    stop_event: threading.Event,
    exa_api_key: str = "",
    openrouter_api_key: str = "",
) -> list[dict]:
```

Два прогресса раздельно: `[Pass 1 — Exa]` и `[Pass 2 — LLM]`.

## enrichments/mx.py

```python
def run_mx_enrichment(
    df: pd.DataFrame,
    url_column: str,
    row_indices: list[int],
    concurrency: int,
    progress_queue: queue.Queue,
    stop_event: threading.Event,
) -> list[dict]:
```

---

# 8) Tab 2 — Settings

```
Working Folder
  Path: [C:/Users/79818/Desktop/leads/    ] [Browse]
  (все CSV из этой папки видны в Table tab)

API Keys
  OpenRouter: [sk-or-...     ] [Show/Hide]
  Exa AI:     [exa-...       ] [Show/Hide]
  [Save to .env]

Defaults
  Concurrency: [50]
  Max tokens:  [1500]
  Confidence threshold: [6]

Prompt Manager
  enrichment/ -- [company_full] [icp_filter] [pain_point] [+ New]
  extraction/ -- [company_deep] [company_full_ext] [+ New]
```

---

# 9) Shared State (main.py)

```python
st.session_state.df             # pd.DataFrame | None
st.session_state.source_file    # str — путь к открытому файлу
st.session_state.working_folder # str — рабочая папка
st.session_state.new_cols       # list[str] — колонки после enrichment (подсветка желтым)
st.session_state.selected_input_cols  # list[str] — выбранные input колонки для enrichment
st.session_state.panel_open     # bool — открыта ли боковая панель
st.session_state.enrichment_type # str — текущий тип enrichment
st.session_state.run_results    # list[dict] | None — результаты последнего рана
```

---

# 10) Progress — паттерн из ai_lead_processing

```python
# enrichments/llm.py — внутри run_llm_enrichment()
import threading, queue, asyncio

def _worker(items, prompt_name, api_key, result_holder, progress_queue, stop_event):
    async def _run():
        # ... extract_batch с кастомным progress callback ...
        for i, result in enumerate(results):
            if stop_event.is_set():
                break
            progress_queue.put_nowait({"done": i+1, "total": len(items), ...})
        result_holder.append(results)
    asyncio.run(_run())

thread = threading.Thread(target=_worker, args=(...))
thread.start()

# В Streamlit enrichment_panel.py:
progress_bar = st.progress(0)
status_text = st.empty()

while thread.is_alive() or not progress_queue.empty():
    try:
        update = progress_queue.get_nowait()
        pct = update["done"] / update["total"]
        progress_bar.progress(pct)
        status_text.text(f"{update['done']}/{update['total']} | ok={update['ok']}")
    except queue.Empty:
        pass
    time.sleep(0.4)

st.rerun()  # только в конце
```

Для scraping — два прогресса раздельно (Pass 1 Exa + Pass 2 LLM):
```python
pass1_queue = queue.Queue()
pass2_queue = queue.Queue()
# каждый обновляется отдельным progress bar в UI
```

**Stop:** `stop_event.set()` → worker проверяет после каждого item → возвращает частичные результаты → можно сохранить.

---

# 11) Acceptance Criteria

- `streamlit run app/main.py` запускается без ошибок
- Working folder задаётся в Settings → CSV файлы появляются в Table tab
- Загрузил CSV → запустил LLM enrichment → выбрал колонки → сохранил → скачал
- Prompt editor: написал `{{Company Name}}` → preview показывает реальное значение
- Column chips: кликнул → `{{Company Name}}` вставился в textarea
- Scraping enrichment: Pass 1 + Pass 2 прогрессы раздельно
- Stop прерывает процесс, частичные результаты можно сохранить
- core/ (exa.py, llm.py, pipeline.py) не импортирует ничего из streamlit
- Новые колонки подсвечиваются желтым до Save/Discard

---

# 12) Порядок реализации

1. `app/main.py` — shared state, st.tabs
2. `app/components/file_browser.py` — рабочая папка + список CSV
3. `app/pages/table.py` — таблица + фильтры + column visibility
4. `app/components/enrichment_panel.py` — shell (input + run + output)
5. `app/components/prompt_editor.py` — textarea + chips + preview + {{}} substitution
6. `app/enrichments/llm.py` — LLM adapter + progress threading
7. `app/enrichments/scraping.py` — Scraping adapter + два прогресса
8. `app/enrichments/mx.py` — MX adapter
9. `app/pages/settings.py` — API keys + working folder + defaults

---

# 13) Архитектурные решения (зафиксировано)

| Вопрос | Решение |
|---|---|
| exa_summary.py | Перенести в archive/ — функциональность в pipeline.py |
| ai_lead_processing/streamlit_app.py | Не копировать — reference только для progress паттерна |
| FastAPI | core/ уже готов (чистые async функции) — обёртки не нужны сейчас |
| {{variable}} в промптах | Двойные фигурные скобки, replace() при рантайме |
| Прогресс в Streamlit | threading.Thread + queue.Queue + get_nowait() + sleep(0.4) |
| Изоляция Streamlit от core | app/enrichments/ адаптер-слой |
| Промпты папки | prompts/enrichment/ + prompts/extraction/ (реорг в TASK-000) |

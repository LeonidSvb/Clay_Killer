---
id: "TASK-006"
title: "app/ — Streamlit UI, Clay-style enrichment workspace"
status: "planned"
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

# 2) Структура файлов

```
WebScraping_Exa/
  app/
    main.py                     ← точка входа, st.tabs, shared state
    pages/
      table.py                  ← Tab 1: таблица + file browser + фильтры
      settings.py               ← Tab 2: API keys + рабочая папка + prompt manager
    components/
      enrichment_panel.py       ← боковая панель (универсальная для всех типов)
      prompt_editor.py          ← dropdown + edit + preview + column chips
      column_selector.py        ← выбор колонок из df (input + output)
      file_browser.py           ← список CSV из рабочей папки
  prompts/
    enrichment/                 ← промпты для LLM enrichment
    extraction/                 ← промпты для web scraping
```

# 3) Два таба

```
[ Table ]   [ Settings ]
```

Всё остальное — в боковой панели (enrichment runner).

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
- После enrichment → сохраняет в ту же папку автоматически
- Download: кнопка рядом с текущим открытым файлом

## Таблица

```
leads_canada.csv | 1702 rows | 19 cols        [Download]  [Columns ▼]  [Filter ▼]

Company Name    │ Website      │ icp_fit  │ confidence  │ summary      │ ...
Sotech Nitram   │ sotech...    │ 8        │ 9           │ Canadian...  │
Service JR      │ service...   │ 7        │ 8           │ Quebec...    │
```

- `[Columns ▼]` — multiselect какие колонки показывать
- `[Filter ▼]` — фильтры: confidence >= N, icp_fit >= N, любая колонка
- Новые колонки после enrichment подсвечиваются желтым до Save/Discard
- `st.dataframe` с `hide_index=True`

## Run Enrichment

```
[ + Run Enrichment ]   ← кнопка внизу или сбоку, открывает панель
```

# 5) Enrichment Panel (боковая панель)

Универсальная структура для всех типов:

```
┌─ Enrichment ──────────────────────────────────────────────┐
│                                                            │
│  Type:  [ LLM Extraction  ▼ ]                             │
│         [ Website Scraping ]                              │
│         [ MX Check         ]                              │
│                                                            │
│  ── [1] INPUT ─────────────────────────────────────────── │
│  Columns going into context:                               │
│  (кликни на заголовок колонки в таблице чтобы добавить)    │
│  Selected: [Website Summary ×] [Company Name ×]           │
│                                                            │
│  ── [2] CONFIG (зависит от type) ──────────────────────── │
│  LLM:      prompt selector + model + concurrency          │
│  Scraping: mode + subpages + deep toggle                  │
│  MX:       concurrency                                     │
│                                                            │
│  ── [3] RUN ───────────────────────────────────────────── │
│  Rows: (●) Preview 10  ( ) All  ( ) Filtered  [    ]      │
│  [ Run ]  [ Stop ]                                        │
│  progress bar + status line                               │
│                                                            │
│  ── [4] OUTPUT (после завершения) ─────────────────────── │
│  Preview: 10 строк результатов                             │
│  Choose columns to save:                                  │
│  [x] summary    → rename: [summary              ]        │
│  [x] icp_fit    → rename: [icp_fit              ]        │
│  [ ] services   (skip)                                    │
│  [ Save to table ]  [ Discard ]                           │
└────────────────────────────────────────────────────────────┘
```

# 6) Prompt Editor (компонент внутри CONFIG для LLM)

```
Prompt: [ company_full  ▼ ]  [✏ Edit]  [+ New]  [🗑 Delete]

┌─ Prompt text ─────────────────────────────────────────────┐
│ Analyse the company below and extract profile.             │
│                                                            │
│ Company: {{Company Name}}                                  │
│ Website summary: {{Website Summary}}                       │
│                                                            │
│ Return JSON: { "summary": ..., "icp_fit": ... }           │
└────────────────────────────────────────────────────────────┘

Available columns (click to insert at cursor):
[Company Name] [Website] [Website Summary] [Industry] [...]

Preview (row 1):
┌───────────────────────────────────────────────────────────┐
│ Analyse the company below and extract profile.             │
│ Company: Sotech Nitram Inc.                               │
│ Website summary: Canadian logistics provider since 1981..  │
└───────────────────────────────────────────────────────────┘

[Save prompt]  (сохраняет в prompts/enrichment/company_full.txt)
```

- `{{column_name}}` подстановка при запуске: `prompt.format(**row.to_dict())`
- Column chips под textarea — кликнул, `{{Column Name}}` вставился
- Preview: берёт первую строку df, показывает финальный текст промпта
- Save: перезаписывает .txt файл на диске
- Delete: confirm dialog → удаляет файл

# 7) Tab 2 — Settings

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
```

# 8) Shared State (main.py)

```python
st.session_state.df            # pd.DataFrame | None
st.session_state.source_file   # str — путь к открытому файлу
st.session_state.working_folder # str — рабочая папка
st.session_state.new_cols      # list[str] — колонки после enrichment (подсветка)
```

# 9) Progress (паттерн из ai_lead_processing)

```python
# threading.Thread + queue.Queue
# get_nowait() inner loop + time.sleep(0.4) + st.rerun() только в конце
# статус: "N/total | X.X/sec | ETA Xs | ok=N | errors=N"
```

Для scraping: два прогресса раздельно (Pass 1 Exa + Pass 2 LLM).

# 10) Acceptance Criteria

- `streamlit run app/main.py` запускается
- Working folder задаётся в Settings → CSV файлы появляются в Table tab
- Загрузил CSV → запустил LLM enrichment → выбрал колонки → сохранил → скачал
- Prompt editor: написал `{{Company Name}}` → preview показывает реальное значение
- Column chips: кликнул → вставилось в textarea
- Scraping enrichment: Pass 1 + Pass 2 прогрессы раздельно
- Stop прерывает процесс, частичные результаты можно сохранить

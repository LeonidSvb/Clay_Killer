---
id: "TASK-007"
title: "UX Design — финальная спецификация"
status: "ready"
priority: "P1"
labels: ["ux", "design", "streamlit"]
dependencies: ["TASK-006"]
created: "2026-03-30"
updated: "2026-03-31"
---

# Статус: СОГЛАСОВАНО — готово к реализации

---

# Архитектура: Clay-style workspace

## Два таба

```
[ Table ]   [ Settings ]
```

Боковая панель = enrichment runner (открывается по кнопке).

---

## Tab 1 — Table

### Верх: File browser

```
┌─────────────────────────────────────────────────────────────┐
│  leads_canada_1700.csv    1702 rows  2026-03-31  [Open]      │
│  us_enriched_500.csv       500 rows  2026-03-31  [Open]      │
│  canada_logistic_deep.csv  100 rows  2026-03-31  [Open]      │
│  [+ Upload CSV]   [Refresh ↺]                               │
└─────────────────────────────────────────────────────────────┘
```

- Сканирует рабочую папку (задана в Settings)
- Refresh или авто-обновление
- После enrichment → сохраняет туда же с суффиксом или перезаписывает

### Тулбар таблицы

```
leads_canada.csv | 1702 rows | 19 cols        [↓ Download]  [Columns ▼]  [Filter ▼]
```

`[Columns ▼]` → multiselect колонок для показа
`[Filter ▼]` → фильтры: любая колонка + оператор + значение
               (confidence >= 6, icp_fit >= 7, exa_status = "ok")

### Таблица

- `st.dataframe`, `hide_index=True`
- Новые колонки после enrichment → желтый фон пока не Save/Discard
- Кликнуть заголовок колонки → выделяется (добавляется в Input enrichment)

### Кнопка

```
[ + Run Enrichment ]   ← открывает боковую панель
```

---

## Enrichment Panel (боковая панель)

### [1] Type selector

```
Type: [ LLM Extraction  ▼ ]
      [ Website Scraping ]
      [ MX Check         ]
```

### [2] Input

```
Input columns (click column headers in table to select):
Selected: [Website Summary ×] [Company Name ×]
```

### [3] Config (зависит от type)

**LLM Extraction:**
```
Prompt: [ company_full ▼ ]  [✏]  [+]  [🗑]

textarea с промптом
(редактируемый если нажать ✏)

Available columns → кликабельные чипы → вставляют {{Column Name}}

Preview (row 1):
┌──────────────────────────────────────┐
│ Analyse: Sotech Nitram Inc.          │
│ Summary: Canadian logistics...       │
└──────────────────────────────────────┘
```

**Website Scraping:**
```
Mode: (●) exa-only  ( ) hybrid  ( ) html-only
[ ] Deep mode    Subpages: [3 ▼]  (если deep включен)
Max chars: [5000]
```

**MX Check:**
```
Concurrency: [50]
```

### [4] Run

```
Rows: (●) Preview 10  ( ) All  ( ) Filtered  ( ) Custom: [100]

[ Run ]  [ Stop ]

████████░░  78/100 | 9.4/sec | ETA 3s | ok=76 | errors=2
```

Для scraping — два прогресса:
```
[Pass 1 — Exa]  ████████░░  40/50 | 7.1/sec | ETA 1s
[Pass 2 — LLM]  ██░░░░░░░░  12/50 | waiting...
```

### [5] Output (после завершения)

```
Preview (10 rows):
Company Name     │ summary (new)           │ icp_fit (new)
Sotech Nitram    │ Canadian logistics...   │ 8
Service JR       │ Quebec mechanic...      │ 7

Choose columns to add:
[x] summary      → [summary              ]  (rename)
[x] icp_fit      → [icp_fit              ]
[ ] services     (skip)
[x] confidence   → [confidence           ]

[ Save to table ]   [ Discard ]
```

---

## Tab 2 — Settings

```
Working Folder
  [C:/Users/79818/Desktop/leads/    ]  [Browse]
  Новые CSV в этой папке автоматически появляются в Table

API Keys
  OpenRouter:  [sk-or-...   ]  [👁]
  Exa AI:      [exa-...     ]  [👁]
  [Save to .env]

Defaults
  Concurrency: [50]    Max tokens: [1500]    Confidence threshold: [6]

Prompt Manager
  enrichment/ ── [company_full] [icp_filter] [pain_point] [+ New]
  extraction/ ── [company_deep] [company_full_ext] [+ New]
```

---

# Prompt editor — детально

```
[ company_full ▼ ]  [✏ Edit]  [+ New]  [🗑 Delete]

При нажатии ✏:

┌─ Edit: company_full ──────────────────────────────────────┐
│                                                            │
│ [textarea — полный текст промпта]                         │
│                                                            │
│ Insert column:                                             │
│ [Company Name] [Website] [Website Summary] [Industry]...  │
│ (кликнул → {{Company Name}} вставился в позицию курсора)  │
│                                                            │
│ Preview — row 1:                                          │
│ ┌──────────────────────────────────────────────────────┐  │
│ │ Analyse the company below:                           │  │
│ │ Company: Sotech Nitram Inc.                         │  │
│ │ Summary: Canadian logistics provider since 1981...  │  │
│ └──────────────────────────────────────────────────────┘  │
│                                                            │
│ [Save]  [Cancel]                                          │
└────────────────────────────────────────────────────────────┘

Delete: "Delete company_full.txt? Type 'delete' to confirm: [      ]"
```

---

# Ключевые UX решения (финальные)

| Вопрос | Решение |
|---|---|
| Где file upload | Tab 1 верх, file browser из рабочей папки |
| История enrichment | Нет. Только save/discard после каждого рана |
| Конфиги | В боковой панели каждого enrichment |
| API keys | Tab 2 Settings |
| Tabs | `st.tabs()`, одна страница |
| Промпты | Dropdown + ✏ edit + preview + column chips |
| `{{variable}}` в промпте | Column chips под textarea, preview обновляется live |
| Новые колонки | Желтая подсветка + save/discard с rename |
| Фильтры | `[Filter ▼]` в тулбаре таблицы |
| Plain text vs JSON output | Авто-определяется: JSON → несколько колонок, текст → одна |
| Тема | Светлая (Streamlit default) |
| Mobile | Не нужно, только desktop |

---

# Порядок реализации (по табам)

1. `main.py` — shared state, st.tabs
2. `components/file_browser.py` — рабочая папка + список CSV
3. `pages/table.py` — таблица + фильтры + column visibility
4. `components/enrichment_panel.py` — shell (input + run + output)
5. `components/prompt_editor.py` — textarea + chips + preview
6. LLM config внутри панели
7. Scraping config внутри панели
8. MX config внутри панели
9. `pages/settings.py`

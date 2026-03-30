---
id: "TASK-007"
title: "UX Design — детальный экран каждого таба"
status: "draft"
priority: "P1"
labels: ["ux", "design", "streamlit"]
dependencies: ["TASK-006"]
created: "2026-03-30"
---

# Статус: НАБРОСОК — требует уточнения с пользователем

Этот таск — детальный UX-документ перед написанием кода.
Цель: не переделывать UI после того как написан код.

---

# Вопросы которые нужно закрыть перед кодом

## Общие

1. Sidebar или нет? Или всё внутри табов через expander?
   - Вариант A: один общий sidebar (API keys + текущие настройки таба)
   - Вариант B: нет sidebar, всё внутри expander в каждом табе
   - Вариант C: sidebar только для API keys, конфиги внутри таба

2. Тёмная/светлая тема? (сейчас в ai_lead_processing есть toggle)

3. Мобильная версия нужна или только desktop?

---

## Tab 1 — LLM Enrichment

**Открытые вопросы:**

- Как выглядит JSON Column Selector?
  - Чекбоксы в expander "Choose output columns"
  - Или таблица preview: поле | пример значения | checkbox
  - Или сначала run → потом выбираешь что сохранить (после первых 5 результатов)

- Где показывается live preview результатов?
  - Таблица под прогресс баром (последние 10 строк)
  - Или отдельный expander
  - Или колонки появляются в главной таблице df в реальном времени

- Как выглядит финальная таблица?
  - Просто st.dataframe (read-only)
  - Или st.data_editor (можно редактировать ячейки)

- Prompt: только dropdown или плюс возможность редактировать текст промпта прямо в UI?

---

## Tab 2 — Web Scraping

**Открытые вопросы:**

- Deep mode toggle: где он? В sidebar или прямо рядом с кнопкой Run?

- Pass 3 retry: нужно ли показывать какие именно URL идут на retry?
  - Просто счётчик "8 URLs → retry"
  - Или список с URL и причиной (confidence=3)

- После завершения: показывать cost breakdown?
  - Exa: $0.019 (19 pages + 0 subpages)
  - LLM: $0.003
  - Total: $0.022

---

## Tab 3 — Utilities

**Открытые вопросы:**

- MX check: показывать распределение провайдеров (пирог/бар) или только таблица?
  - Google: 45% | Microsoft: 30% | Other: 25%

- Какие ещё утилиты планируются? (чтобы сделать правильный layout)
  - Email validation?
  - Domain extractor из email?
  - Deduplicate?

---

## Общий df / таблица

**Открытые вопросы:**

- Где показывается текущий df?
  - В каждом табе внизу
  - Или отдельный таб "Table" / "Preview"
  - Или всегда виден в нижней части страницы

- Можно ли удалять строки из df в UI?

- Фильтры по колонкам нужны? (показать только fit=true, например)

---

# Набросок экранов (нужно подтвердить)

## Верхняя часть (всегда видна)

```
[Logo / название]          current_file: leads_us.csv | 1347 rows | 19 cols  [Clear]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[  LLM Enrichment  ] [  Web Scraping  ] [  Utilities  ]
```

## Tab 1 — LLM Enrichment (черновик)

```
┌─ Settings ──────────────────────────────────────────────────────────────────┐
│  Prompt:  [company_full          ▼]   Input col: [Website Summary      ▼]  │
│  Model:   [openai/gpt-oss-120b    ]   Limit:     [500    ]  Concur: [50 ] │
└─────────────────────────────────────────────────────────────────────────────┘

┌─ Output columns ────────────────────────────────────────────────────────────┐
│  Detected from prompt schema:                                               │
│  [x] summary    [x] icp_fit    [x] geography    [ ] services    [x] b2b   │
│  [x] confidence [ ] target_market               [ ] company_size_estimate  │
└─────────────────────────────────────────────────────────────────────────────┘

[ Run 500 leads ]  [ Stop ]

████████████░░░░░░░  234/500 | 9.4/sec | ETA 28s | ok=231 | low_conf=34

┌─ Live results (last 10) ────────────────────────────────────────────────────┐
│  URL                      summary (preview)          icp_fit   confidence  │
│  franklinfitch.com        IT infrastructure rec...   9         9           │
│  consea-group.com         Human capital consult...   8         9           │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Tab 2 — Web Scraping (черновик)

```
┌─ Settings ──────────────────────────────────────────────────────────────────┐
│  Mode: (o) exa-only  ( ) hybrid    URL col: [Company Website ▼]            │
│  Prompt: [company_full ▼]           Text col (hybrid): [Website Summary ▼] │
│  Subpages: [3]  [ ] Deep mode       Limit: [100]                           │
└─────────────────────────────────────────────────────────────────────────────┘

[ Run ]  [ Stop ]

[Pass 1] Exa:    ████████░░  40/50 | 7.1/sec | ETA 1s
[Pass 2] LLM:    ░░░░░░░░░░  waiting...
[Pass 3] Retry:  —

Cost estimate: ~$0.041  (40 pages × $0.001 + est. LLM)
```

---

# Следующий шаг

Пройтись по открытым вопросам с пользователем, уточнить, обновить набросок → потом кодить Tab 1.

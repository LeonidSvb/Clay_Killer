---
id: "TASK-006"
title: "app/ — Streamlit UI (обзор, разбит на подзадачи)"
status: "ready"
priority: "P1"
labels: ["ui", "streamlit", "architecture"]
dependencies: ["TASK-004", "TASK-005"]
created: "2026-03-30"
updated: "2026-03-31"
---

# Обзор

Clay-style workspace. Разбит на 3 последовательных подзадачи:

| Подзадача | Файл | Что делает | Статус |
|---|---|---|---|
| TASK-006a | TASK-006a-skeleton.md | main.py + table + file browser + settings | ready |
| TASK-006b | TASK-006b-panel.md | Enrichment panel + Prompt editor + LLM adapter | ready |
| TASK-006c | TASK-006c-scraping-mx.md | Scraping adapter + MX adapter + polish | ready |

Запуск: `streamlit run app/main.py`

# Структура файлов (итоговая)

```
WebScraping_Exa/
  app/
    main.py
    pages/
      table.py
      settings.py
    components/
      enrichment_panel.py
      prompt_editor.py
      column_selector.py
      file_browser.py
    enrichments/
      llm.py
      scraping.py
      mx.py
  prompts/
    enrichment/
    extraction/
```

# Архитектура enrichments/ (адаптер-слой)

`core/` — чистые async функции, нет зависимостей от Streamlit.
`app/enrichments/` — обёртки через `threading.Thread + queue.Queue`.

Философия: каждый enrichment — атомарный блок.
`pipeline.py` = пресет для CLI (хардкоженная цепочка).
Streamlit = ручная цепочка блоков.
Workflow presets (post-MVP) = сохранённая цепочка enrichments.

# Типы enrichments (текущие + planned)

| Тип | Статус | Где |
|---|---|---|
| LLM Extraction | MVP | enrichments/llm.py |
| Website Scraping (Exa) | MVP | enrichments/scraping.py |
| MX Check | MVP | enrichments/mx.py |
| API Call (email validation) | post-MVP | enrichments/api_call.py |
| Waterfall column | post-MVP | enrichments/waterfall.py |
| Boolean Aggregation | post-MVP | enrichments/boolean_agg.py |
| Workflow preset (chain) | post-MVP | — |

# Shared State

```python
st.session_state.df
st.session_state.source_file
st.session_state.working_folder
st.session_state.new_cols
st.session_state.selected_input_cols
st.session_state.panel_open
st.session_state.enrichment_type
st.session_state.run_results
```

# Architectural decisions

См. `docs/decisions.md` ADR-004 ({{column}}), ADR-005 (enrichments/ adapter).

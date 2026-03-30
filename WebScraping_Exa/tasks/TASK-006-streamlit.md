---
id: "TASK-006"
title: "streamlit_app.py — UI поверх pipeline core/"
status: "planned"
priority: "P2"
labels: ["ui", "streamlit"]
dependencies: ["TASK-005"]
created: "2026-03-30"
---

# 1) High-Level Objective

Написать `streamlit_app.py` — UI обёртка над готовым pipeline.
Импортирует core/ модули напрямую (не subprocess).
CSV upload → настройки → run → progress → download.

# 2) Background / Context

Паттерны из соседнего проекта:
  C:\Users\79818\Desktop\tests\ai_lead_processing\streamlit_app.py
  - threading.Thread + queue.Queue для async в Streamlit
  - get_nowait() inner loop + time.sleep(0.4) + st.rerun() только в конце
  - 4 метрики после завершения
  - hide_index=True в dataframe

# 3) Assumptions & Constraints

- Constraint: CSV only (нет Google Sheets write-back)
- Constraint: промпты = файлы из prompts/ (dropdown, не text_area редактор на старте)
- Constraint: деплой локально сначала, потом на сервер (нет auth)

# 4) Dependencies

- core/*.py (TASK-001 — TASK-004)
- pipeline.py (TASK-005) — логика оркестрации
- C:\Users\79818\Desktop\tests\ai_lead_processing\streamlit_app.py _(read-only, паттерны)_

# 5) Context Plan

**Beginning:**
- pipeline.py _(read-only)_
- core/*.py _(read-only)_
- C:\Users\79818\Desktop\tests\ai_lead_processing\streamlit_app.py _(read-only)_

**End state:**
- streamlit_app.py

# 6) Low-Level Steps

1. **Структура UI — три зоны:**
   ```
   Sidebar: API ключи, режим, промпт, concurrency, confidence threshold
   Main:    Upload → Config → Run → Progress → Results
   ```

2. **Sidebar:**
   - EXA_API_KEY (type=password, из .env дефолт)
   - OPENROUTER_API_KEY (type=password, из .env дефолт)
   - Mode: radio ["hybrid", "exa-only", "scraper-only"]
   - Prompt: selectbox из list_prompts() (core/llm.py)
   - Concurrency: slider 10-100, дефолт 50
   - Confidence threshold: slider 1-9, дефолт 6

3. **Upload + авто-детект колонок:**
   - st.file_uploader CSV
   - Авто-детект URL колонки (по имени + контенту)
   - Авто-детект существующей summary колонки
   - Selectbox для подтверждения / изменения

4. **Метрики после upload:**
   ```
   Total rows | Already processed | No URL | Ready to process
   ```

5. **Лимит + режим:**
   - Radio: 50 / 100 / 500 / All / Custom
   - Info: "Will process N leads"

6. **Columns selector (после первого результата или заранее):**
   - st.multiselect с полями из промпта
   - Preview: поле → пример значения
   - Если колонка уже есть в CSV → предупреждение overwrite

7. **Run / Stop кнопки:**
   - Disabled если нет API ключа или нет лидов
   - Показывать почему disabled (st.warning)

8. **Progress (паттерн из ai_lead_processing):**
   ```python
   # threading.Thread запускает pipeline
   # queue.Queue передаёт результаты
   # inner while loop с get_nowait() + time.sleep(0.4)
   # st.rerun() только в конце
   ```
   Статус строка:
   ```
   N/total | X.X/sec | ETA MM:SS | Pass3: N | errors: N
   ```
   Таблица последних 15 результатов:
   ```
   url | summary (120 chars) | icp_fit | ok
   ```

9. **Results:**
   - 4 метрики: Processed / Success% / Time / ~Cost
   - st.data_editor с результатами (можно редактировать ячейки)
   - Download enriched CSV (все колонки)
   - Download results only (только обработанные строки)
   - Failed rows expander
   - "Process more" кнопка (не сбрасывает загруженный файл)

10. **~Cost расчёт:**
    ```python
    exa_pages = n_exa_pass1 + n_exa_pass3 * subpages
    exa_cost  = exa_pages * 0.001
    llm_cost  = n_processed * avg_input_chars / 4 * 0.000000039  # приблизительно
    total_cost = exa_cost + llm_cost
    ```

# 8) Acceptance Criteria

- Запускается: `py -m streamlit run streamlit_app.py`
- Upload CSV, Run 20 лидов — видно прогресс в реальном времени
- Download работает
- Stop прерывает процесс
- Sidebar настройки влияют на запуск

# 9) Testing Strategy

- Запустить на тест-файле 314e74cc...csv, limit=20, hybrid режим
- Проверить что progress обновляется каждые ~0.4 сек (не зависает)
- Проверить download: открыть CSV, убедиться что все колонки на месте
- Проверить Stop: нажать в середине, убедиться что результаты частично сохранены

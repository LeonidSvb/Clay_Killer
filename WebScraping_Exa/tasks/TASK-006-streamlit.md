---
id: "TASK-006"
title: "app/ — Streamlit UI, 3 таба, с нуля"
status: "planned"
priority: "P1"
labels: ["ui", "streamlit", "architecture"]
dependencies: ["TASK-004", "TASK-005"]
created: "2026-03-30"
updated: "2026-03-30"
---

# 1) High-Level Objective

Написать Streamlit-приложение внутри `WebScraping_Exa/app/`.
Три таба: LLM Enrichment / Web Scraping / Utilities.
Один общий DataFrame живёт в `st.session_state` на всё время сессии.
CSV загружается один раз — дальше таблица обновляется действиями.

# 2) Структура файлов

```
WebScraping_Exa/
  app/
    main.py             ← точка входа, навигация, shared state
    pages/
      llm.py            ← Tab 1
      scraping.py       ← Tab 2
      utilities.py      ← Tab 3
  prompts/
    enrichment/         ← промпты для LLM таба (берут текст из колонки)
      icp_filter.txt
      pain_point.txt
      industry.txt
      current_method.txt
      icebreaker.txt    ← выносим из ai_lead_processing (был захардкожен)
    extraction/         ← промпты для Scraping таба (что достать с сайта)
      company_full.txt
      company_deep.txt
      company_profile.txt
      icp_score.txt
```

Запуск: `streamlit run app/main.py`

# 3) Shared State (main.py)

```python
# session_state инициализируется один раз при старте
st.session_state.df          # pd.DataFrame | None — рабочая таблица
st.session_state.source_file # str — имя загруженного файла
```

Загрузка CSV в `main.py` (не внутри табов):
- file_uploader вверху страницы, всегда виден
- После загрузки: `st.session_state.df = pd.read_csv(uploaded)`
- Имя файла показывается рядом: "leads_us.csv | 1347 rows | 17 cols"
- Кнопка "Clear" — сбрасывает df

# 4) Tab 1 — LLM Enrichment

**Источник**: берёт текст из выбранной колонки df → прогоняет через LLM → добавляет колонки.

**Конфиги (sidebar или expander):**
- OpenRouter API Key (password, из .env дефолт)
- Model (text input, дефолт gpt-oss-120b)
- Prompt: dropdown из `prompts/enrichment/*.txt`
- Input column: selectbox из колонок df
- Concurrency: slider 10-100
- Limit: number_input (0 = all)

**JSON Column Selector (ключевая фича):**
- Если промпт возвращает JSON (все наши enrichment промпты) — показать чекбоксы
- Список полей определяется из первых 3-5 результатов (не до запуска)
- По умолчанию все поля выбраны
- Пользователь снимает галочки с ненужных
- Только отмеченные поля добавляются как колонки в df
- Если поле уже есть в df — предупреждение, предлагает `_v2` или overwrite

**Plain text режим:**
- Если промпт возвращает не JSON — создаётся одна колонка с именем из поля "Output column"

**Progress (паттерн из ai_lead_processing):**
- threading.Thread + queue.Queue
- get_nowait() inner loop + time.sleep(0.4) + st.rerun() только в конце
- progress bar + статус: "N/total | X.X/sec | ETA Xs | ok=N | errors=N"
- Live таблица последних 10 результатов

**После завершения:**
- df обновлён (новые колонки добавлены)
- 4 метрики: Processed / OK% / Time / ~Cost
- Download кнопка (текущий df целиком)
- "Run more" — не сбрасывает df, можно выбрать другой промпт

# 5) Tab 2 — Web Scraping

**Источник**: берёт URL из выбранной колонки df → Exa fetch → LLM extraction → добавляет колонки.

**Конфиги:**
- EXA_API_KEY (password, из .env дефолт)
- OpenRouter API Key (из shared state)
- Mode: radio [exa-only | hybrid (existing text + Exa для пустых)]
- Prompt: dropdown из `prompts/extraction/*.txt`
- URL column: selectbox
- Text column (для hybrid): selectbox, optional
- Subpages: slider 0-5 (0 = Pass 3 disabled)
- Deep mode: toggle (subpages=5, max_chars=15000, company_deep prompt)
- Limit: number_input

**Progress — три фазы раздельно:**
```
[Pass 1] Exa fetch:   ████░░ 23/50 | 7.2/sec | ETA 4s
[Pass 2] LLM:         ██████ 50/50 | 9.1/sec | done
[Pass 3] Retry (8):   ███░░░ 4/8   | 0.4/sec | ETA 10s
```

**JSON Column Selector** — та же логика что в Tab 1.

**После завершения:**
- df обновлён
- Метрики: OK / low_conf / retried / time / exa_cost / llm_cost
- Download

# 6) Tab 3 — Utilities

**MX Provider Check** (логика из ai_lead_processing, скопирована, не импортирована):
- Email column selectbox
- Concurrency slider
- Run → добавляет колонки `mx_real`, `mx_provider` в df
- Progress: get_nowait() паттерн

**Placeholder для будущих утилит:**
- "Email cleanup" (в планах)
- "Domain extractor" (в планах)

# 7) Что НЕ делать

- Не импортировать из `ai_lead_processing/` — только скопировать MX логику
- Не делать Google Sheets write-back
- Не делать scraper-only режим (TASK-002 не готов)
- Не делать /configs YAML пока — промпты в .txt достаточно
- Не делать /components пока — потом, когда появится реальное дублирование

# 8) Зависимости

```python
# app/main.py imports:
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))  # WebScraping_Exa/ в path
from core.exa import fetch_batch
from core.llm import extract_batch, list_prompts, CONFIDENCE_THRESHOLD
from core.prescreener import screen_batch
from pipeline import run as pipeline_run
```

# 9) Acceptance Criteria

- `streamlit run app/main.py` запускается без ошибок
- Загрузил CSV → переключил таб → df виден в обоих табах
- Tab 1: run 20 строк → видно прогресс → новые колонки появились в df → download работает
- Tab 2: run 10 URLs в exa-only → три фазы прогресса → колонки добавлены
- Tab 3: MX check 20 emails → колонки mx_real, mx_provider добавлены
- Stop прерывает процесс, частичные результаты сохраняются в df

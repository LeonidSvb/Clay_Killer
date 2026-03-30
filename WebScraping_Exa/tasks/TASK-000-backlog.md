---
id: "TASK-000"
title: "Backlog — мелкие недоделки и улучшения"
status: "open"
priority: "P2"
labels: ["backlog", "polish"]
created: "2026-03-31"
updated: "2026-03-31"
---

# Сессия 2026-03-31 — что сделано

## Архитектурные решения (ADR)
- Убран `max_tokens` из payload OpenRouter — модели дешёвые, качество важнее (ADR-007)
- Убран `max_llm_chars` из pipeline.py — GPT-OSS-120b контекст 128k, cap был хаком (ADR-002)
- Каждый Streamlit app получает фиксированный порт через `.streamlit/config.toml` (ADR-008)

## Файлы добавлены / изменены
- `core/llm.py` — убран DEFAULT_MAX_TOKENS, убран max_tokens из payload
- `pipeline.py` — убран --max-llm-chars аргумент и вся логика truncation
- `docs/decisions.md` — ADR-002, ADR-007 обновлены; ADR-008 добавлен (порты)
- `.streamlit/config.toml` — port=8501, headless=true, runOnSave=true
- `run.bat` — один клик запуск с kill занятого порта
- `kill_ports.ps1` — убивает порты 8502-8510
- `tasks/TASK-006-streamlit.md` — переделан в индекс с таблицей типов enrichments
- `tasks/TASK-006a-skeleton.md` — полная спецификация скелета
- `tasks/TASK-006b-panel.md` — спецификация панели + LLM адаптера
- `tasks/TASK-006c-scraping-mx.md` — спецификация scraping + MX адаптеров

## TASK-006a (скелет) — DONE ✓
- `app/main.py` — session_state из .env, две вкладки Table + Settings
- `app/components/file_browser.py` — compact dropdown, csv.reader для подсчёта строк, upload toggle
- `app/pages/table.py` — fill% в заголовках колонок, фильтры (8 операторов), Download
- `app/pages/settings.py` — авто-загрузка .env, show/hide API keys, save через python-dotenv

## TASK-006b (панель + LLM адаптер) — DONE ✓
- `app/enrichments/llm.py` — threading+queue адаптер, два режима промптов:
  - `prompts/enrichment/*.txt` → `{{column_name}}` замена через replace()
  - `prompts/*.txt` → `{text}` замена через format() (legacy CLI промпты)
  - per-request прогресс через asyncio.as_completed + queue.Queue
- `app/components/prompt_editor.py` — selector с Edit/New/Delete, chip кнопки вставляют `{{col}}`, preview row 1
- `app/components/enrichment_panel.py` — полная панель: input cols, prompt editor, concurrency,
  radio (Preview 10/All/Filtered/Custom), progress bar в реальном времени,
  run summary stats (boolean%/categorical/numeric), save-to-table с rename, discard
- `app/pages/table.py` — layout 3|2 через st.columns когда panel_open=True
- `tests/test_006b.py` — 13 тестов, все прошли

---

# СЛЕДУЮЩАЯ СЕССИЯ — ручное тестирование TASK-006a + 006b

## Порядок тестирования (от и до)

### 1. Запуск
```
Запусти run.bat из WebScraping_Exa/ или через tests/run.bat → выбери [1]
Открывается http://localhost:8501
```

### 2. File Browser
- [ ] В поле "Working folder" вписать путь к папке с CSV (или через Settings)
- [ ] Dropdown показывает список файлов в формате `filename.csv  (512 rows, 03-31)`
- [ ] Клик [Open] загружает файл → таблица появляется
- [ ] Toggle "Upload new file" → загрузить CSV → он появляется в dropdown
- [ ] Кол-во строк в dropdown совпадает с реальным (особенно на CSV с многострочными полями)

### 3. Таблица
- [ ] Колонки в заголовках показывают fill%: `Company Name (87%)`
- [ ] Download — скачивается файл
- [ ] Columns popover — скрыть/показать колонки, "Show all" возвращает все
- [ ] Фильтр "=" — отфильтровать по точному значению
- [ ] Фильтр "contains" — частичное совпадение
- [ ] Фильтр "is empty" — только пустые строки
- [ ] Фильтр "is not empty" — только заполненные строки
- [ ] Фильтр ">=" — числовое сравнение
- [ ] Caption показывает "N of M rows (filtered)" при активном фильтре
- [ ] "Clear all filters" сбрасывает

### 4. Settings
- [ ] Вкладка Settings — поля OpenRouter Key, Exa Key, Working Folder, Concurrency
- [ ] Значения загружаются из .env автоматически
- [ ] Show/Hide ключи работает
- [ ] Save сохраняет в .env и в os.environ
- [ ] После Save вернуться на Table — working folder применился без перезапуска

### 5. Enrichment Panel — открытие
- [ ] Кнопка [+ Run Enrichment] открывает панель справа
- [ ] Таблица смещается влево (layout 3:2)
- [ ] [X Close] закрывает панель, layout возвращается

### 6. Prompt Editor
- [ ] Dropdown показывает все промпты из prompts/ и prompts/enrichment/
- [ ] Выбрать `company_full` → textarea показывает содержимое (read-only)
- [ ] [Edit] → textarea становится редактируемой
- [ ] Чипы с именами колонок появляются под textarea
- [ ] Клик на чип [Company Name] → `{{Company Name}}` добавляется в конец текста
- [ ] Expander "Preview (row 1)" показывает промпт с реальными данными из первой строки
- [ ] [Save prompt] сохраняет в prompts/enrichment/company_full.txt
- [ ] [Cancel edit] отменяет изменения
- [ ] [+ New] → ввести имя → создаётся новый файл с шаблоном
- [ ] [Delete] → ввести 'delete' → файл удаляется

### 7. LLM Enrichment — запуск
- [ ] Input columns: выбрать колонку с текстом (Website Summary или похожее)
- [ ] Prompt: выбрать company_full
- [ ] Concurrency: оставить 50
- [ ] Rows: Preview 10
- [ ] [Run] → прогресс-бар обновляется в реальном времени
- [ ] После завершения: "X/10 | ok=Y | errors=Z"
- [ ] Preview таблица показывает первые 10 результатов
- [ ] Run summary: icp_fit → % true/false, confidence → avg/min/max, summary → N unique values

### 8. Save / Discard
- [ ] Снять галочку с ненужной колонки (например "raw")
- [ ] Переименовать колонку: "icp_fit" → "icp_score"
- [ ] [Save to table] → новые колонки появляются в таблице с жёлтым фоном
- [ ] Панель закрывается автоматически
- [ ] Новые колонки видны в Columns popover
- [ ] Повторное открытие файла сбрасывает жёлтый фон (new_cols очищается)
- [ ] [Discard] → результаты не сохраняются, таблица не изменилась

---

# Что дальше (TASK-006c)

- Scraping adapter — Exa scraping прямо из панели (тип "Website Scraping")
- MX Check adapter — тип "MX Check" без LLM
- Stop handling — реальная остановка по клику
- Два progress bar'а (scraping + LLM) для Waterfall



# Мелкие недоделки (делать по ходу или перед релизом)

## pipeline.py

- [ ] **Ретрай failed Exa URLs** — сейчас `exa_status=empty_results` просто пропускается.
      Добавить `--retry-failed` флаг: взять строки где `exa_status != ok` → повторить с другим
      max_age_hours (например 72h вместо 24h) или без subpages

- [ ] **Прогресс Pass 3** — добавить лейбл "[Pass 3 Exa]" / "[Pass 3 LLM]"

- [ ] **--overwrite по умолчанию** — при повторном запуске колонки получают суффикс `_llm`.
      Добавить `--overwrite` как дефолт когда колонки LLM уже существуют (спрашивать или авто)

- [ ] **Логирование в файл** — добавить `--log output.log` чтобы весь stdout писался в файл
      параллельно с выводом на экран

## prompts/

- [ ] **Реорганизация папок** — разложить по `prompts/enrichment/` и `prompts/extraction/`
      согласно TASK-006. Сейчас всё в корне `prompts/`

- [ ] **icebreaker.txt** — вынести захардкоженный промпт из `ai_lead_processing/streamlit_app.py`
      в `prompts/enrichment/icebreaker.txt`

- [ ] **relevant_observation.txt** — промпт из SSM библиотеки ещё не добавлен
      (Variable 3: наблюдение о компании для email opener)

## core/llm.py

- [ ] **cost_usd в LLMResult** — добавить поле `cost_usd` из `usage.cost` в OpenRouter ответе.
      Нужно для Run Summary stats (показывать стоимость прогона в $).
      OpenRouter возвращает это поле когда `usage` есть в ответе.

- [ ] **Retry на HTTP 429** — если OpenRouter возвращает 429 (rate limit) → подождать 2s и retry
      один раз. Сейчас это просто error

- [ ] **Стоимость в результате** — добавить в LLMResult поле `cost_usd` из `usage.cost`
      если OpenRouter его возвращает

## core/exa.py

- [ ] **max_age_hours как параметр CLI** — в `fetch_batch()` уже есть, но в CLI не пробрасывается
      через pipeline. Добавить `--max-age-hours` в pipeline.py

## Качество данных

- [ ] **Benchmark: homepage vs deep** — чёткая таблица когда что использовать:
      массовый прогон → homepage | финальный энричмент топ-лидов → deep

---

# Post-MVP фичи (Streamlit)

## Email validation enrichments

Атомарные enrichments для проверки email. Каждый — отдельный тип в панели "API Call".

- [ ] **Mailco validation** — input: email колонка → output: `mailco_status` (valid/invalid/catch-all/unknown)
      Дешёвый, хорошо покрывает ~60% базы

- [ ] **Million Verifier (через Epify)** — input: email колонка → output: `mv_status`
      Для оставшихся после Mailco

- [ ] **Catch-all domain checker** — input: email/domain → output: `catchall_status`
      Для доменов где другие валидаторы говорят catch-all

- [ ] **Email waterfall** — объединение трёх выше через Waterfall column:
      `email_verified` = первый "valid" из mailco → mv → catchall
      Итого: 60% + 20% + 10% = ~90% покрытие из трёх источников

## Waterfall column

- [ ] **Waterfall enrichment** — пользователь выбирает [col_A, col_B, col_C] →
      финальная колонка = первое непустое значение.
      Usecase: email из трёх источников, website из трёх источников.

## Boolean aggregation column

- [ ] **Boolean aggregation** — объединение true/false колонок в решение:
      пользователь выбирает колонки + оператор (AND / OR).
      Пример: `tam_ok AND ships_us AND is_b2b → qualified`.
      Каждая колонка заполнена на 20-40%, пересечение — финальный ICP список.
      Usecase: 5 отдельных LLM enrichments (каждый проверяет один критерий) →
      объединяешь в `qualified` без нового LLM вызова.

## Workflow presets (saved chains)

- [ ] **Saved workflow** — сохранённая цепочка enrichments как пресет:
      пример "Email verification" = Mailco → MV → Catchall → Waterfall.
      Запускается одной кнопкой на любом CSV.
      pipeline.py = пример такого пресета для CLI.

---

# Deep mode — архитектура (требует исследования)

Текущий подход: все страницы Exa → один текст → один LLM вызов → summary + scoring.
Проблема: при 5 subpages summary может терять информацию с отдельных страниц.

Три варианта:

- [ ] **Вариант A — Page-by-page facts extraction**
      Каждая страница → LLM извлекает сухие факты → финальный LLM объединяет
      Плюс: ни одна страница не теряется
      Минус: N+1 LLM вызовов, дороже

- [ ] **Вариант B — Весь текст в контекст (текущий, без лимитов)**
      GPT-OSS-120b контекст 128k → 75k chars входит (5 subпages × 15k chars)
      max_tokens и max_llm_chars убраны — тестируем качество
      Проверить: confidence avg на 100 deep лидах без каких-либо лимитов

- [ ] **Вариант C — Per-page summary → финальный синтез**
      Каждая страница → короткий summary (3-5 предложений)
      Все mini-summaries → финальный LLM синтезирует
      Плюс: компактный финальный контекст, нет потерь
      Минус: дороже варианта B, дешевле варианта A

      Рекомендация: сначала тестировать Вариант B. Если confidence низкий — Вариант C.

---

# Низкий приоритет / может не понадобиться

- [ ] **TASK-002 scraper.py** — кастомный scraper для html_light сайтов (~8% аудитории)

- [ ] **Дедупликация по URL** — один URL встречается несколько раз → обработать один раз

- [ ] **--dry-run** — прогнать без LLM, только Exa, показать статистику текста

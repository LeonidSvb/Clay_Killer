# PRD: LLM Testing Lab v2

## Цель
Инструмент для тестирования LLM outputs: сравниваем модели и/или промпты,
оцениваем через судью, видим результаты в одной динамической таблице.

---

## Файловая структура

```
gradio/
  config.py      — MODELS dict, константы
  core.py        — call_model(), run_experiment() (генератор), агрегация
  app.py         — только Gradio UI
  results/       — автосохранение JSON
  PRD.md
  run.bat
  .env
```

---

## config.py

### MODELS
Словарь: `{ display_name: { "id": str, "in": float, "out": float } }`

Список моделей:
- Llama 3.1 70B / Llama 3.3 70B / Llama 4 Maverick
- GPT-4o / GPT-4o Mini / GPT-OSS 120B
- DeepSeek R1 / DeepSeek V3
- Qwen 2.5 72B / Mistral Large
- Claude 3.5 Haiku / Claude Sonnet 4.5
- Gemini 2.0 Flash

### Константы
```python
RESULTS_DIR = "results/"
DEFAULT_N_OUTPUTS = 15
DEFAULT_TEMPERATURE = 0.7
MAX_PROMPT_SLOTS = 5
API_TIMEOUT = 45
```

---

## core.py

### call_model(model_key, prompt, temperature) -> dict
- Один промпт, летит как `user` message (system пустой)
- Возвращает: `{ text, tokens_in, tokens_out, cost_float, latency_s, error }`
- timeout=45, extra_body={"provider": {"sort": "throughput"}}

### parse_judge_output(text) -> dict
- Извлекает JSON из ответа судьи
- Возвращает все ключи как есть — динамика
- Overall вычисляется у нас: среднее всех числовых значений (исключая ключ "overall" если он есть)
- При ошибке парсинга: `{ "parse_error": text[:80] }`

### build_configs(models, prompts, temperature) -> list[Config]
```python
Config = {
    "model":       str,   # display name
    "prompt":      str,   # текст промпта
    "prompt_idx":  int,   # номер слота (1, 2, ...)
    "temperature": float,
}
```
Результат: все комбинации models × prompts (температура одна).

### run_experiment(models, prompts, temperature, n_outputs, judge_models, judge_prompt)
**Генератор** — yield-ит словарь обновлений Gradio компонентов на каждом шаге.

Этапы:
1. Генерация: для каждого конфига вызываем call_model → получаем n_outputs текстов
   - Параллельно через ThreadPoolExecutor(max_workers=20)
   - После каждого завершённого конфига: yield статус "Генерация: K/N конфигов..."
2. Скоринг: для каждого (output, judge) вызываем call_model с judge_prompt
   - Параллельно через ThreadPoolExecutor(max_workers=30)
   - После каждых 10 завершённых оценок: yield статус "Скоринг: K/N оценок..."
3. Финал: yield полные результаты (таблица, статистика, сохранение)

### aggregate(raw_results) -> pd.DataFrame
- Входные данные raw_results: list of row dicts
- Динамические колонки: строковые поля сначала, числовые потом, Overall последний
- Возвращает отсортированный по Overall (desc) DataFrame

### save_results(config_snapshot, raw_results) -> str
- Сохраняет JSON в results/YYYYMMDD_HHMMSS.json
- Возвращает путь файла

### fmt_cost(v) -> str
- Человекочитаемый формат стоимости

---

## app.py — UI

### Компоненты (сверху вниз)

```
gr.Markdown("# LLM Testing Lab")

[Accordion "Настройки" open=True]
  Row:
    Col(scale=2):
      "Промпты"
      [prompt_1: gr.Textbox, lines=4, label="Промпт 1"]
      [prompt_2: gr.Textbox, lines=4, visible=False, label="Промпт 2"]
      [prompt_3: gr.Textbox, lines=4, visible=False, label="Промпт 3"]
      [prompt_4: gr.Textbox, lines=4, visible=False, label="Промпт 4"]
      [prompt_5: gr.Textbox, lines=4, visible=False, label="Промпт 5"]
      [btn_add_prompt: Button "+  промпт", size="sm"]
      [prompt_count: gr.State(1)]

    Col(scale=1):
      "Модели и параметры"
      [models_dd: gr.Dropdown(multiselect=True)]  — дефолт: Llama 3.3 70B, GPT-4o Mini, Gemini 2.0 Flash
      [temperature: gr.Slider(0.0, 2.0, value=0.7, step=0.05)]
      [n_outputs: gr.Slider(5, 50, value=15, step=5)]

    Col(scale=1):
      "Судья"
      [judge_dd: gr.Dropdown(multiselect=True)]  — дефолт: GPT-4o Mini
      [judge_prompt: gr.Textbox(lines=10)]

[Group]
  [plan_box: gr.Markdown]  — автообновляется при изменении любого input

[btn_run: gr.Button("Запустить", variant="primary", size="lg")]

[status_box: gr.Textbox(label="Статус", interactive=False)]  — обновляется через yield

[Row]
  [filter_min: gr.Slider(0, 10, value=0, label="Overall min")]
  [filter_max: gr.Slider(0, 10, value=10, label="Overall max")]
  [filter_model: gr.Dropdown(["Все модели"], label="Модель")]
  [filter_prompt: gr.Dropdown(["Все промпты"], label="Промпт")]

[results_table: gr.Dataframe(wrap=True)]

[Row]
  [save_label: gr.Textbox(interactive=False)]
```

### Состояние
```python
raw_state = gr.State([])   — список raw row dicts после run
```

### Events

**btn_add_prompt.click**
- inputs: [prompt_count]
- outputs: [prompt_2..5 visibility, prompt_count]
- логика: если count < 5, показываем следующий слот, count += 1

**любой input настройки.change → update_plan**
- inputs: [models_dd, prompt_1..5, prompt_count, temperature, n_outputs, judge_dd]
- outputs: [plan_box]
- логика: считаем N конфигов, N оценок, примерную стоимость, время

**btn_run.click → run_experiment (генератор)**
- inputs: [models_dd, prompt_1..5, prompt_count, temperature, n_outputs, judge_dd, judge_prompt]
- outputs: [status_box, results_table, filter_model, filter_prompt, save_label, raw_state]
- генератор yield-ит промежуточные обновления status_box
- финальный yield: заполненная таблица + обновлённые фильтры + путь сохранения

**filter_*.change → apply_filters**
- inputs: [raw_state, filter_min, filter_max, filter_model, filter_prompt]
- outputs: [results_table]
- логика: фильтруем raw_state по Overall и по выбранным значениям

---

## Схема данных

### raw row (одна запись = один output, оценённый одним судьёй)
```python
{
    "model":       str,
    "prompt_idx":  int,
    "temperature": float,
    "judge":       str,
    "output":      str,          # полный текст генерации
    "output_short":str,          # первые 120 символов для таблицы
    # динамические поля из JSON судьи (строки и числа):
    "verdict":     str,          # если судья вернул текстовое поле
    "creativity":  float,        # пример числового критерия
    # ...любые другие ключи...
    "overall":     float,        # вычислено нами = среднее числовых
}
```

### Порядок колонок в таблице
1. model
2. prompt_idx
3. temperature
4. judge
5. output_short
6. [все строковые поля из судьи]
7. [все числовые поля из судьи, кроме overall]
8. overall

### JSON файл в results/
```json
{
  "timestamp": "2026-04-01 17:00:00",
  "config": {
    "models": [...],
    "prompts": [...],
    "temperature": 0.7,
    "n_outputs": 15,
    "judge_models": [...],
    "judge_prompt": "..."
  },
  "stats": {
    "total_configs": N,
    "total_outputs": N,
    "total_evaluations": N,
    "gen_cost_usd": 0.0,
    "eval_cost_usd": 0.0,
    "total_cost_usd": 0.0
  },
  "rows": [ ...raw rows... ]
}
```

---

## Предпросмотр (plan_box)

Формат:
```
3 модели × 2 промпта × 15 выходов = 90 генераций | 90 × 1 судья = 90 оценок | 180 вызовов
~$0.0042 | ~35 сек
```

Две строки, только самое важное.

---

## Папка с промптами

```
gradio/
  prompts/       — все промпты (генерация + судьи) в одном месте
    my_prompt.txt
    judge_strict.txt
    ...
```

### Логика в UI (у каждого слота промпта и у судейского промпта)
- Дропдаун "Загрузить" — список всех `.txt` из `prompts/`, при выборе вставляет текст в поле
- Кнопка "Сохранить" → появляется поле ввода названия → кнопка "OK" → сохраняет в `prompts/{название}.txt`, обновляет дропдаун

### Функции в core.py
```python
list_prompts() -> list[str]          # имена файлов без .txt
load_prompt(name) -> str             # читает файл
save_prompt(name, text) -> str       # сохраняет, возвращает путь
```

---

## Таблица — поведение ячеек

- В таблице показываем `output_short` = первые 120 символов
- При клике на ячейку Gradio показывает полный текст (стандартное поведение `gr.Dataframe(wrap=True)`)
- Это работает нативно в Gradio — дополнительного кода не нужно

---

## Фильтры

Фильтровать можно по **любому числовому критерию** из последнего запуска.
Поскольку критерии динамические, фильтры генерируются динамически после каждого run:

```python
# После run: для каждого числового поля создаём слайдер мин-макс
numeric_cols = [c for c in df.columns if df[c].dtype in (float, int)
                and c not in ("prompt_idx", "temperature")]
# → overall, creativity, resonance, etc.
```

В UI: `gr.State` хранит список числовых колонок текущего запуска.
Фильтры рендерятся через `gr.Column` с динамическим содержимым после run.

Простое решение без динамического рендера: один универсальный фильтр —
`filter_col: gr.Dropdown` (выбираешь колонку) + `filter_min/max: gr.Slider`.
После run dropdown обновляется списком числовых колонок.

---

## Что НЕ делаем (сознательно убрано)
- System prompt (всё в один user prompt)
- Frequency penalty
- Max tokens слайдеры
- Пресеты
- Отдельные вкладки с аналитикой (По моделям, По судьям и т.д.)
- Сравнение с предыдущими запусками
- Radar/bar/box charts
- Ручное сохранение (только автосохранение)
- gr.Progress() — заменён на yield + status_box

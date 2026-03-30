---
id: "TASK-006a"
title: "Streamlit skeleton — main.py + table + file browser + settings"
status: "ready"
priority: "P1"
labels: ["ui", "streamlit"]
dependencies: ["TASK-006"]
created: "2026-03-31"
---

# Что делаем

Запускаемый скелет приложения. После этой части:
`streamlit run app/main.py` открывается, CSV загружается, таблица видна, settings работает.
Enrichment panel — заглушка (кнопка есть, панель пустая).

---

# Файлы

```
app/
  main.py
  pages/
    table.py
    settings.py
  components/
    file_browser.py
```

---

# app/main.py

```python
import streamlit as st
from pages.table import render_table
from pages.settings import render_settings

st.set_page_config(page_title="Lead Enrichment", layout="wide")

# Shared state init
defaults = {
    "df": None,
    "source_file": None,
    "working_folder": "",
    "new_cols": [],
    "selected_input_cols": [],
    "panel_open": False,
    "enrichment_type": "LLM Extraction",
    "run_results": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

tab1, tab2 = st.tabs(["Table", "Settings"])

with tab1:
    render_table()

with tab2:
    render_settings()
```

---

# app/components/file_browser.py

Сканирует рабочую папку, показывает список CSV.

```
leads_canada_1700.csv    1702 rows   2026-03-31   [Open]
us_enriched_500.csv       500 rows   2026-03-31   [Open]
[+ Upload CSV]   [Refresh]
```

- `Path(folder).glob("*.csv")` — сортировка по дате изменения (новые вверху)
- `[Open]` → `pd.read_csv()` → `st.session_state.df` + `st.session_state.source_file`
- `[+ Upload CSV]` → `st.file_uploader` → сохраняет в working_folder → обновляет список
- `[Refresh]` → `st.rerun()`
- Если working_folder не задан → показывает предупреждение "Set working folder in Settings"

---

# app/pages/table.py

```
leads_canada.csv | 1702 rows | 19 cols    [Download]  [Columns v]  [Filter v]

Company Name  | Website   | icp_fit | confidence | summary    |
Sotech Nitram | sotech... | 8       | 9          | Canadian...|

[ + Run Enrichment ]
```

## Тулбар

- Имя файла + размер (из session_state.source_file + df.shape)
- `[Download]` → `st.download_button` с CSV в памяти
- `[Columns v]` → `st.multiselect` из df.columns, фильтрует видимые колонки
- `[Filter v]` → `st.expander` с фильтрами:
  - selectbox выбор колонки
  - selectbox оператор (=, !=, >=, <=, contains)
  - text_input значение
  - Кнопка "+ Add filter", список активных фильтров с [x]

## Таблица

```python
# Желтый фон для новых колонок после enrichment
def highlight_new_cols(df):
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    for col in st.session_state.new_cols:
        if col in df.columns:
            styles[col] = "background-color: #fff9c4"
    return styles

st.dataframe(
    filtered_df[visible_cols].style.apply(highlight_new_cols, axis=None),
    hide_index=True,
    use_container_width=True,
)
```

## Кнопка Run Enrichment

```python
if st.button("+ Run Enrichment", type="primary"):
    st.session_state.panel_open = True
    st.rerun()
```

Если `panel_open=True` → рендерит заглушку панели справа (в этой части пустая).

---

# app/pages/settings.py

```
Working Folder
  [C:/Users/79818/Desktop/leads/    ]  [Browse]

API Keys
  OpenRouter:  [sk-or-v1-...  ] [Show/Hide]
  Exa AI:      [exa-...       ] [Show/Hide]
  [Save to .env]

Defaults
  Concurrency: [50]   Confidence threshold: [6]
```

- Working folder: `st.text_input` + валидация `Path.exists()`
- Browse: нет нативного folder picker в Streamlit → просто text_input с подсказкой
- API keys: `st.text_input(type="password")` + toggle через session_state
- Save to .env: перезаписывает `.env` файл в корне проекта
- Загружает текущие значения из `.env` при открытии (через `python-dotenv`)
- Defaults сохраняются в session_state и используются как дефолты в enrichment panel

---

# Тесты

## Автоматические (в конце задачи)

```python
# smoke test — запускается через: python -m pytest tests/test_smoke.py
def test_imports():
    import app.main  # не падает при импорте
    from app.pages.table import render_table
    from app.pages.settings import render_settings
    from app.components.file_browser import render_file_browser

def test_session_state_defaults():
    # проверяем что все ключи инициализируются
    expected = ["df", "source_file", "working_folder", "new_cols",
                "selected_input_cols", "panel_open", "enrichment_type", "run_results"]
    # читаем main.py, проверяем что все ключи есть в defaults dict
    import ast, pathlib
    src = pathlib.Path("app/main.py").read_text()
    for key in expected:
        assert f'"{key}"' in src
```

## Ручной тест (для тебя)

После `streamlit run app/main.py` открывается `http://localhost:8501`

1. **Settings tab:**
   - Введи рабочую папку с CSV файлами
   - Введи API keys
   - Нажми [Save to .env] → проверь что .env обновился

2. **Table tab — file browser:**
   - Видишь список CSV из рабочей папки
   - Нажми [Open] на любом файле → таблица появляется
   - Нажми [Refresh] → список обновляется

3. **Table tab — таблица:**
   - Нажми [Columns v] → сними пару колонок → они исчезают из таблицы
   - Нажми [Filter v] → добавь фильтр `confidence >= 7` → строки фильтруются
   - Нажми [Download] → скачивается CSV

4. **Run Enrichment:**
   - Нажми [+ Run Enrichment] → что-то появляется (заглушка или пустая панель)

---

# Acceptance Criteria

- [ ] `streamlit run app/main.py` запускается без ошибок
- [ ] Working folder → файлы появляются в file browser
- [ ] [Open] → таблица загружается
- [ ] [Columns v] → колонки скрываются/показываются
- [ ] [Filter v] → строки фильтруются
- [ ] [Download] → скачивается CSV
- [ ] [Save to .env] → .env обновляется
- [ ] core/ не импортирует ничего из streamlit (проверить grep)

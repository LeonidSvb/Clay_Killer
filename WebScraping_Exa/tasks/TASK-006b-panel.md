---
id: "TASK-006b"
title: "Streamlit — Enrichment Panel + Prompt Editor + LLM adapter"
status: "ready"
priority: "P1"
labels: ["ui", "streamlit"]
dependencies: ["TASK-006a"]
created: "2026-03-31"
---

# Что делаем

LLM enrichment работает end-to-end:
загрузил CSV → открыл панель → выбрал промпт → запустил → видишь прогресс → сохранил колонки.

---

# Файлы

```
app/
  components/
    enrichment_panel.py   <- универсальная боковая панель
    prompt_editor.py      <- textarea + {{}} chips + preview
  enrichments/
    llm.py                <- LLM adapter (threading + queue)
```

---

# app/components/enrichment_panel.py

Структура панели (рендерится в st.sidebar или st.expander):

```
Type: [ LLM Extraction v ]
      [ Website Scraping ]
      [ MX Check         ]

-- [1] INPUT --
Input columns:
[Website Summary x]  [Company Name x]
+ Add column: [ select... v ]

-- [2] CONFIG --
(зависит от type — см. ниже)

-- [3] RUN --
Rows: (o) Preview 10  ( ) All  ( ) Filtered  ( ) Custom: [   ]
[ Run ]  [ Stop ]
████████░░  78/100 | 9.4/sec | ETA 3s | ok=76 | errors=2

-- [4] OUTPUT --
Preview (первые 10 строк результата):
Company Name     | summary (new)      | icp_fit (new)
Sotech Nitram    | Canadian logi...   | 8

Choose columns to add:
[x] summary   -> [summary    ]  (rename)
[x] icp_fit   -> [icp_fit    ]
[ ] services  (skip)
[ Save to table ]   [ Discard ]
```

## CONFIG для LLM Extraction

```python
# Prompt selector
prompt_name = st.selectbox("Prompt", list_prompts())
# кнопка edit → разворачивает prompt_editor компонент
if st.button("Edit"):
    st.session_state.show_prompt_editor = True

# Concurrency
concurrency = st.number_input("Concurrency", value=50, min_value=1, max_value=200)
```

## Save to table

```python
# Применяет результаты к df
for result in st.session_state.run_results:
    idx = result["idx"]
    for col_key, col_name in rename_map.items():
        if col_key in result["data"]:
            st.session_state.df.at[idx, col_name] = result["data"][col_key]

# Помечает новые колонки для подсветки
st.session_state.new_cols.extend(list(rename_map.values()))
st.session_state.run_results = None
st.rerun()
```

---

# app/components/prompt_editor.py

```
[ company_full v ]  [Edit]  [+ New]  [Delete]

+- textarea (только чтение если не Edit mode) ------+
| Analyse the company below:                        |
| Company: {{Company Name}}                         |
| Summary: {{Website Summary}}                      |
| Return JSON: {...}                                |
+---------------------------------------------------+

Insert column:
[Company Name]  [Website]  [Website Summary]  [Industry]  [...]

Preview — row 1:
+---------------------------------------------------+
| Analyse the company below:                        |
| Company: Sotech Nitram Inc.                       |
| Summary: Canadian logistics provider since 1981.. |
+---------------------------------------------------+

[Save]  [Cancel]
```

## Реализация column chips

```python
# Chips под textarea
cols_in_row = st.columns(min(len(df.columns), 5))
for i, col in enumerate(df.columns):
    with cols_in_row[i % 5]:
        if st.button(col, key=f"chip_{col}"):
            # Добавляем в конец textarea через session_state
            current = st.session_state.get("prompt_text", "")
            st.session_state.prompt_text = current + f" {{{{col}}}}"
            st.rerun()
```

Примечание: нативная вставка в позицию курсора в Streamlit не поддерживается.
Workaround: добавляем в конец. Если нужна вставка в курсор — использовать `streamlit-ace`.

## Preview

```python
def render_preview(prompt_template: str, df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return prompt_template
    row = df.iloc[0]
    filled = prompt_template
    for col in df.columns:
        filled = filled.replace("{{" + col + "}}", str(row.get(col, "")))
    return filled

st.code(render_preview(prompt_text, st.session_state.df))
```

## Save / Delete

```python
# Save
Path(f"prompts/enrichment/{prompt_name}.txt").write_text(prompt_text, encoding="utf-8")

# Delete — confirm через text input
confirm = st.text_input("Type 'delete' to confirm")
if confirm == "delete":
    Path(f"prompts/enrichment/{prompt_name}.txt").unlink()
    st.rerun()
```

---

# app/enrichments/llm.py

```python
import asyncio, threading, queue, time
import pandas as pd
from core.llm import extract_batch

def run_llm_enrichment(
    df: pd.DataFrame,
    input_columns: list[str],
    prompt_name: str,
    row_indices: list[int],
    concurrency: int,
    progress_queue: queue.Queue,
    stop_event: threading.Event,
    api_key: str = "",
) -> list[dict]:
    """
    Запускает LLM enrichment в текущем потоке (вызывается из threading.Thread).
    Возвращает список {"idx": int, "data": dict, "ok": bool}.
    """
    items = []
    for idx in row_indices:
        row = df.iloc[idx]
        # Заполняем {{column_name}} из input_columns
        text_parts = []
        for col in input_columns:
            val = str(row.get(col, "")).strip()
            if val and val not in ("nan", "None"):
                text_parts.append(f"{col}: {val}")
        text = "\n".join(text_parts)
        items.append({"url": str(idx), "text": text, "idx": idx})

    results_holder = []

    async def _run():
        raw = await extract_batch(
            [{"url": it["url"], "text": it["text"]} for it in items],
            prompt_name=prompt_name,
            concurrency=concurrency,
            api_key=api_key,
        )
        # Пробрасываем прогресс построчно (extract_batch уже сделал всё)
        total = len(raw)
        ok_count = sum(1 for r in raw if r.ok)
        err_count = total - ok_count
        progress_queue.put_nowait({
            "done": total, "total": total,
            "ok": ok_count, "errors": err_count,
        })
        results_holder.extend(raw)

    asyncio.run(_run())

    # Маппим обратно по idx
    url_to_idx = {str(it["idx"]): it["idx"] for it in items}
    return [
        {"idx": url_to_idx[r.url], "data": r.data, "ok": r.ok, "error": r.error}
        for r in results_holder
        if r.url in url_to_idx
    ]
```

## Как вызывается из enrichment_panel.py

```python
import threading, queue

progress_queue = queue.Queue()
stop_event = threading.Event()
results_holder = []

def worker():
    results = run_llm_enrichment(
        df=st.session_state.df,
        input_columns=selected_input_cols,
        prompt_name=prompt_name,
        row_indices=row_indices,
        concurrency=concurrency,
        progress_queue=progress_queue,
        stop_event=stop_event,
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
    )
    results_holder.extend(results)

thread = threading.Thread(target=worker, daemon=True)
thread.start()

# Progress loop
progress_bar = st.progress(0)
status = st.empty()
while thread.is_alive() or not progress_queue.empty():
    try:
        upd = progress_queue.get_nowait()
        pct = upd["done"] / upd["total"] if upd["total"] > 0 else 0
        progress_bar.progress(pct)
        status.text(f"{upd['done']}/{upd['total']} | ok={upd['ok']} | errors={upd['errors']}")
    except queue.Empty:
        pass
    time.sleep(0.4)

st.session_state.run_results = results_holder
st.rerun()
```

---

# Run Summary (stats после завершения)

Показывается сразу после OUTPUT preview, до Save/Discard.

```
Run completed in 12.4s  |  1000 processed  |  ok: 967  |  errors: 33

Column: icp_fit
  True:  312  (32%)  ██████░░░░
  False: 655  (68%)  █████████░

Column: industry
  logistics:       34%  ██████░░░░
  manufacturing:   28%  █████░░░░░
  retail:          18%  ████░░░░░░
  construction:    12%  ██░░░░░░░░
  other:            8%  ██░░░░░░░░

Column: confidence
  avg: 7.2  /  min: 3  /  max: 10

Column: summary
  847 unique values  (не показываем breakdown)
```

## Логика отображения

```python
def render_run_summary(results: list[dict], elapsed: float):
    st.caption(f"Completed in {elapsed:.1f}s | "
               f"ok={sum(r['ok'] for r in results)} | "
               f"errors={sum(not r['ok'] for r in results)}")

    # Собираем все output колонки
    all_keys = set()
    for r in results:
        if r["ok"]:
            all_keys.update(r["data"].keys())
    all_keys.discard("raw")

    for key in sorted(all_keys):
        values = [r["data"].get(key) for r in results if r["ok"] and key in r["data"]]
        if not values:
            continue

        unique = set(str(v) for v in values)

        if len(unique) <= 8:
            # Breakdown с процентами
            from collections import Counter
            counts = Counter(str(v) for v in values)
            total = len(values)
            st.write(f"**{key}**")
            for val, cnt in counts.most_common():
                pct = cnt / total * 100
                st.write(f"  {val}: {cnt} ({pct:.0f}%)")

        elif all(isinstance(v, (int, float)) for v in values):
            # Числовая колонка → avg/min/max
            nums = [float(v) for v in values]
            st.write(f"**{key}**: avg {sum(nums)/len(nums):.1f} / "
                     f"min {min(nums)} / max {max(nums)}")

        else:
            # Много уникальных → только count
            st.write(f"**{key}**: {len(unique)} unique values")
```

Cost tracking (USD) — не сейчас. Добавить когда LLMResult.cost_usd будет готов (TASK-000 backlog).

---

# Тесты

## Автоматические

```python
def test_prompt_preview():
    import pandas as pd
    from app.components.prompt_editor import render_preview
    df = pd.DataFrame([{"Company Name": "Acme Corp", "Website": "acme.com"}])
    template = "Company: {{Company Name}}, site: {{Website}}"
    result = render_preview(template, df)
    assert result == "Company: Acme Corp, site: acme.com"

def test_llm_enrichment_interface():
    # Проверяем что функция принимает нужные аргументы
    import inspect
    from app.enrichments.llm import run_llm_enrichment
    params = inspect.signature(run_llm_enrichment).parameters
    assert "df" in params
    assert "input_columns" in params
    assert "prompt_name" in params
    assert "progress_queue" in params
    assert "stop_event" in params
```

## Ручной тест (для тебя)

1. **Открой панель:** нажми [+ Run Enrichment]

2. **Prompt editor:**
   - Выбери промпт `company_full` в dropdown
   - Нажми [Edit]
   - Нажми на chip `[Company Name]` → `{{Company Name}}` добавляется в текст
   - В Preview видишь реальное имя компании из первой строки CSV

3. **Запуск LLM enrichment:**
   - Input columns: выбери `Website Summary` (или другую текстовую колонку)
   - Rows: Preview 10
   - Нажми [Run]
   - Видишь прогресс-бар и `10/10 | ok=9 | errors=1`

4. **Save результата:**
   - В Output preview видишь новые колонки
   - Сними галочку с ненужной колонки
   - Переименуй колонку если нужно
   - Нажми [Save to table]
   - В таблице появляются новые колонки с **желтым фоном**

5. **Discard:** нажми [Discard] → результаты не сохраняются, желтого нет

---

# Acceptance Criteria

- [ ] Prompt editor: chip → `{{column}}` вставляется, preview обновляется
- [ ] LLM enrichment запускается, прогресс-бар обновляется
- [ ] Stop прерывает выполнение, частичные результаты доступны
- [ ] Run summary: boolean колонки → % true/false, categorical (<=8) → breakdown, numeric → avg/min/max, unique → count
- [ ] Save → новые колонки с желтым фоном в таблице
- [ ] Discard → изменений нет
- [ ] Новый промпт создаётся и сохраняется в prompts/enrichment/
- [ ] Delete промпта с подтверждением работает

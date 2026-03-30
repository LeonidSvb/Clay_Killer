---
id: "TASK-006c"
title: "Streamlit — Scraping adapter + MX adapter + polish"
status: "ready"
priority: "P1"
labels: ["ui", "streamlit"]
dependencies: ["TASK-006b"]
created: "2026-03-31"
---

# Что делаем

Все три типа enrichment работают. Два прогресс-бара для scraping.
Stop с сохранением частичных результатов. Финальный polish.

---

# Файлы

```
app/
  enrichments/
    scraping.py   <- Exa fetch + LLM extraction, два прогресса
    mx.py         <- MX DNS check
```

---

# app/enrichments/scraping.py

Два прогресс-бара: Pass 1 (Exa) + Pass 2 (LLM).

```python
import asyncio, threading, queue, time
import pandas as pd
from core.exa import fetch_batch
from core.llm import extract_batch

def run_scraping_enrichment(
    df: pd.DataFrame,
    url_column: str,
    prompt_name: str,
    row_indices: list[int],
    mode: str,              # "exa-only" | "hybrid" | "html-only"
    subpages: int,
    max_chars: int,
    concurrency: int,
    pass1_queue: queue.Queue,   # прогресс Exa fetch
    pass2_queue: queue.Queue,   # прогресс LLM
    stop_event: threading.Event,
    exa_api_key: str = "",
    openrouter_api_key: str = "",
) -> list[dict]:
    """
    Возвращает список {"idx": int, "data": dict, "ok": bool, "exa_status": str}.
    """
    urls = []
    idx_map = {}  # url -> row index
    for idx in row_indices:
        if stop_event.is_set():
            break
        row = df.iloc[idx]
        url = str(row.get(url_column, "")).strip()
        if url and url not in ("nan", "None"):
            if not url.startswith(("http://", "https://")):
                url = "http://" + url
            urls.append(url)
            idx_map[url] = idx

    if not urls:
        return []

    results = []

    async def _run():
        # Pass 1 — Exa
        exa_results = await fetch_batch(
            urls,
            concurrency=concurrency,
            subpages=subpages,
            text_max_chars=max_chars,
            api_key=exa_api_key,
        )
        ok_exa = [r for r in exa_results if r.ok]
        pass1_queue.put_nowait({
            "done": len(exa_results), "total": len(urls),
            "ok": len(ok_exa), "errors": len(exa_results) - len(ok_exa),
        })

        if stop_event.is_set() or not ok_exa:
            # Возвращаем exa_status для всех
            for r in exa_results:
                if r.url in idx_map:
                    results.append({
                        "idx": idx_map[r.url],
                        "data": {},
                        "ok": False,
                        "exa_status": "ok" if r.ok else (r.error or "unknown").split(":")[0],
                        "exa_chars": r.total_chars,
                    })
            return

        # Pass 2 — LLM
        items = [{"url": r.url, "text": r.total_text} for r in ok_exa]
        llm_results = await extract_batch(
            items,
            prompt_name=prompt_name,
            concurrency=concurrency,
            api_key=openrouter_api_key,
        )
        ok_llm = sum(1 for r in llm_results if r.ok)
        pass2_queue.put_nowait({
            "done": len(llm_results), "total": len(items),
            "ok": ok_llm, "errors": len(llm_results) - ok_llm,
        })

        # Маппим exa_status для всех URL
        exa_status_map = {
            r.url: ("ok" if r.ok else (r.error or "unknown").split(":")[0])
            for r in exa_results
        }
        exa_chars_map = {r.url: r.total_chars for r in exa_results}

        for r in llm_results:
            if r.url in idx_map:
                results.append({
                    "idx": idx_map[r.url],
                    "data": r.data if r.ok else {},
                    "ok": r.ok,
                    "error": r.error,
                    "exa_status": exa_status_map.get(r.url, "unknown"),
                    "exa_chars": exa_chars_map.get(r.url, 0),
                })

        # Добавляем строки где Exa упал
        llm_urls = {r.url for r in llm_results}
        for r in exa_results:
            if not r.ok and r.url in idx_map:
                results.append({
                    "idx": idx_map[r.url],
                    "data": {},
                    "ok": False,
                    "exa_status": exa_status_map.get(r.url, "unknown"),
                    "exa_chars": 0,
                })

    asyncio.run(_run())
    return results
```

## CONFIG в enrichment_panel.py для Scraping

```
Mode: (o) exa-only  ( ) hybrid  ( ) html-only
[ ] Deep mode
  Subpages: [3 v]   (если Deep включен)
Max chars per page: [5000]
Concurrency: [50]
```

## Два прогресс-бара в UI

```python
st.write("**Pass 1 — Exa fetch**")
pass1_bar = st.progress(0)
pass1_status = st.empty()

st.write("**Pass 2 — LLM extraction**")
pass2_bar = st.progress(0)
pass2_status = st.empty()

while thread.is_alive() or not pass1_queue.empty() or not pass2_queue.empty():
    for q, bar, status in [
        (pass1_queue, pass1_bar, pass1_status),
        (pass2_queue, pass2_bar, pass2_status),
    ]:
        try:
            upd = q.get_nowait()
            pct = upd["done"] / upd["total"] if upd["total"] > 0 else 0
            bar.progress(pct)
            status.text(f"{upd['done']}/{upd['total']} | ok={upd['ok']} | errors={upd['errors']}")
        except queue.Empty:
            pass
    time.sleep(0.4)
```

---

# app/enrichments/mx.py

MX DNS check — определяет email провайдера по домену.

```python
import asyncio, threading, queue
import pandas as pd

def run_mx_enrichment(
    df: pd.DataFrame,
    url_column: str,
    row_indices: list[int],
    concurrency: int,
    progress_queue: queue.Queue,
    stop_event: threading.Event,
) -> list[dict]:
    """
    Возвращает список {"idx": int, "data": {"mx_provider": str, "mx_real": str}, "ok": bool}.
    """
    # Импортируем существующую логику из core/mx.py (или ai_lead_processing)
    from core.mx import check_mx_batch  # если уже есть

    domains = []
    idx_map = {}
    for idx in row_indices:
        row = df.iloc[idx]
        url = str(row.get(url_column, "")).strip()
        domain = extract_domain(url)
        if domain:
            domains.append(domain)
            idx_map[domain] = idx

    results_holder = []

    async def _run():
        mx_results = await check_mx_batch(domains, concurrency=concurrency)
        total = len(mx_results)
        ok = sum(1 for r in mx_results if r.get("ok"))
        progress_queue.put_nowait({"done": total, "total": total, "ok": ok, "errors": total - ok})
        results_holder.extend(mx_results)

    asyncio.run(_run())

    return [
        {
            "idx": idx_map[r["domain"]],
            "data": {"mx_provider": r.get("provider", ""), "mx_real": r.get("mx_real", "")},
            "ok": r.get("ok", False),
        }
        for r in results_holder
        if r["domain"] in idx_map
    ]
```

## CONFIG в enrichment_panel.py для MX

```
URL/Domain column: [ Website v ]
Concurrency: [50]
```

Output columns: `mx_provider`, `mx_real`

---

# Polish (входит в эту задачу)

## Stop с частичными результатами

```python
if st.button("Stop"):
    stop_event.set()
    # После thread.join() — показываем OUTPUT секцию с тем что успело обработаться
    # Пользователь может сохранить частичные результаты
    st.warning(f"Stopped. {len(results_holder)} rows processed.")
```

## exa_status и exa_chars в Output

После scraping enrichment — дополнительные колонки:
```
[x] exa_status  -> [exa_status]
[x] exa_chars   -> [exa_chars ]
```
Всегда предлагать сохранить чтобы видеть какие URL упали.

## Финальный smoke test всего приложения

```python
def test_full_app_import():
    from app.enrichments.llm import run_llm_enrichment
    from app.enrichments.scraping import run_scraping_enrichment
    from app.enrichments.mx import run_mx_enrichment
    # Все три импортируются без ошибок

def test_core_no_streamlit():
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-c",
         "import core.llm, core.exa; print('ok')"],
        capture_output=True, text=True
    )
    assert "ok" in result.stdout
    assert "streamlit" not in result.stderr
```

---

# Ручной тест (для тебя)

1. **Scraping enrichment:**
   - Открой панель → выбери "Website Scraping"
   - URL column: выбери колонку с сайтами
   - Rows: Preview 5
   - Нажми [Run]
   - Видишь два прогресс-бара: Pass 1 заполняется, потом Pass 2
   - В Output: summary + exa_status + exa_chars

2. **Stop mid-run:**
   - Запусти на All rows большого CSV
   - Нажми [Stop] через 3-5 секунд
   - Видишь "Stopped. N rows processed."
   - Можешь сохранить частичные результаты

3. **MX Check:**
   - Открой панель → "MX Check"
   - URL column: колонка с сайтами
   - Rows: All
   - Нажми [Run]
   - В Output: mx_provider (Google / Microsoft / Other), mx_real

---

# Acceptance Criteria

- [ ] Scraping enrichment: Pass 1 + Pass 2 прогрессы раздельно
- [ ] Stop прерывает выполнение, частичные результаты сохраняемы
- [ ] exa_status + exa_chars предлагаются в Output колонках
- [ ] MX Check работает, возвращает mx_provider + mx_real
- [ ] Все 3 типа enrichment работают в одной панели через Type selector
- [ ] core/ не импортирует streamlit (финальная проверка)

# AI Lead Processing

Инструменты для обработки лидов: генерация айсбрейкеров + проверка MX провайдеров.

---

## Запуск Streamlit

```bash
cd C:\Users\79818\Desktop\tests\ai_lead_processing
streamlit run streamlit_app.py
```

Откроется в браузере: **http://localhost:8501**

Если порт занят (другой инстанс уже запущен):

```bash
streamlit run streamlit_app.py --server.port 8510
```

Остановить: `Ctrl+C` в терминале.

---

## Табы

### Icebreaker Generator
Генерация персональных opening line для cold email через OpenRouter.
Настройки — в сайдбаре. Поддерживает CSV, Google Sheets (Apps Script), Google Sheets (Service Account).

### MX Provider Check
Определяет email провайдера по домену через DNS (Google DoH API).

**Результат — 2 колонки:**
- `mx_real` — итоговый провайдер: `Google` / `Microsoft` / `Microsoft (gateway)` / `Mimecast` / `Unknown` / `No MX`
- `mx_provider` — что стоит на MX напрямую: `Google` / `Hornetsecurity` / `Sophos` / `Proofpoint Essentials` и т.д.

---

## Python скрипт (без Streamlit)

```bash
# Отредактируй INPUT/OUTPUT вверху файла, затем:
py scripts/discovery/2026-03-30-mx-provider-final.py
```

---

## Файлы

| Файл | Назначение |
|------|-----------|
| `streamlit_app.py` | Основной UI |
| `scripts/discovery/2026-03-30-mx-provider-final.py` | MX check CLI скрипт |
| `google_apps_script.js` | Apps Script для прямого доступа к Google Sheets |
| `n8n-reference.md` | Референс по n8n: credentials, workflows, MX workflow |
| `CHANGELOG.md` | История изменений |

---

## Переиспользуемые паттерны

Готовые блоки для следующих проектов — просто дай этот README в контекст.

### 1. Параллельные запросы к OpenRouter

**Файл:** `run_icebreakers.py` (функции `_batch` + `_one`) и `streamlit_app.py` (функции `_batch` + `_one`)

```python
# Ключевые параметры запроса:
{
    "model": "openai/gpt-oss-120b",
    "provider": {"sort": "throughput"},  # ОБЯЗАТЕЛЬНО — иначе 7x медленнее
    "max_tokens": 500,                   # для reasoning моделей нужно 500+
}
# Паттерн параллелизма: asyncio.Semaphore + asyncio.as_completed
# concurrency=50 → ~14 leads/sec, 2000 лидов за ~2.3 мин
# Бенчмарки: scripts/discovery/2026-03-30-*.py
```

**Важно:** `sort: "throughput"` обязателен — дефолтный роутинг идёт на SiliconFlow (самый дешёвый = медленный). С throughput OpenRouter сам распределяет запросы по нескольким провайдерам автоматически.

---

### 2. Streamlit: прогресс-бар для долгих async задач

**Файл:** `streamlit_app.py`, блок `if run_state == "running"`

Паттерн: async в отдельном `threading.Thread`, результаты передаются через `queue.Queue`, Streamlit читает очередь в цикле с `time.sleep(0.4)` и обновляет UI.

```python
# Ключевые компоненты:
threading.Thread(target=_thread_runner, daemon=True).start()
# В цикле:
prog_bar.progress(n_done / total)
status_ph.markdown(f"{n_done}/{total} | {speed:.1f}/sec | ETA {eta_str} | ${cost:.4f}")
table_ph.dataframe(pd.DataFrame(last_15_results))
# Stop button через threading.Event
```

---

### 3. Streamlit: конфиг с персистентностью

**Файл:** `streamlit_app.py`, функции `load_config` / `save_config`

```python
# DEFAULTS dict → merge с JSON файлом → st.session_state.cfg
# Save config кнопка пишет в icebreaker_config.json
# При следующем запуске всё восстанавливается
```

---

### 4. Async DNS lookup (MX check)

**Файл:** `streamlit_app.py`, функции `_mx_fetch` + `_mx_batch`
**CLI версия:** `scripts/discovery/2026-03-30-mx-provider-final.py`

```python
# Google DoH API: https://dns.google/resolve?name={domain}&type=MX
# concurrency=50, retry x3 на 429
# Классификация: MX_DIRECT список + MX_GATEWAYS dict + SPF fallback
# Результат: mx_real (Google/Microsoft/gateway/Unknown) + mx_provider (raw name)
```

---

### 5. Google Sheets без credentials (Apps Script)

**Файл:** `google_apps_script.js`

Деплоишь как Web App (Anyone), получаешь URL. GET → читает pending rows, POST → batch write по row_number. Работает без OAuth, без service account. Ограничение: один скрипт = одна таблица.

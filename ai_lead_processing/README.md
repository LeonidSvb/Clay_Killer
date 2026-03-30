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

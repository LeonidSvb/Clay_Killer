# Changelog — sales-calls-fathom

## 2026-03-26 — Initial build

### Added
- `scripts/sync-calls.js` — скачивает все звонки из Fathom API (транскрипты, саммари, action items), сохраняет JSON + CSV
- `scripts/generate-import-csv.js` — генерирует CSV в формате Google Sheets с AI-анализом (нужен ANTHROPIC_API_KEY)
- `scripts/backfill-sheet.js` — отправляет все локальные звонки через n8n webhook для пакетного анализа
- `scripts/test-webhook.js` — тестирует production webhook с реальным звонком
- `scripts/create-n8n-workflow.js` — создаёт основной воркфлоу в n8n (однократный запуск)
- `scripts/update-n8n-workflow.js` — обновляет воркфлоу: модель, Sheet ID, активирует
- `scripts/create-backfill-workflow.js` — создаёт воркфлоу для ретроактивного анализа из Google Sheets
- `data/calls-library.csv` — сырые данные всех звонков (без AI-анализа)
- `data/calls-import.csv` — CSV для импорта в Google Sheets (колонки совместимы с n8n)
- `.env` — API ключи (не коммитится)

### N8N Workflows создано
- `031gIgLPBlR0KbpM` — **SALES - Fathom -> Sales Calls Library** (active)
  - Trigger: Fathom webhook POST после каждого звонка
  - Model: GPT-OSS 120B via Groq
  - Output: строка в Google Sheets с полным AI-анализом
- `m6Faw8aHLdxHbAUk` — **SALES - Backfill Analysis from Sheets** (manual)
  - Читает строки без Outcome из Google Sheets
  - Подтягивает транскрипты из Fathom API
  - Анализирует GPT-OSS 120B, обновляет строки

### Fathom Webhook зарегистрирован
- ID: `Wy8j_zgK_nj_Vsdx`
- URL: `https://n8n.srv1133622.hstgr.cloud/webhook/fathom-sales-calls`
- Triggers: my_recordings + transcript + summary + action_items

### Google Sheets
- ID: `1kLHxA4fOmeVTyaVaAgPPS4cqoNf85lq1m0pUCuyC6pM`
- Колонки: Date, Prospect, Duration (min), Leo Talk %, Outcome, Engagement, Leo Confidence, Key Objection, Buying Signals, What Worked, Biggest Mistake, Next Step, Action Items, Summary, Recording ID, Fathom URL

### Stats сессии
- Звонков скачано: 11 (5ч 49мин суммарно)
- Все с транскриптами
- Звонков проанализировано через GPT-OSS 120B: 11 (backfill)

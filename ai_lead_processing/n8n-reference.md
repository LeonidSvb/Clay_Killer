# N8N Control Reference
> Последнее обновление: 2026-03-26

---

## Инстанс

| Параметр | Значение |
|---|---|
| VPS URL | https://n8n.srv1133622.hstgr.cloud |
| API Key | в .env файле: `N8N_API_KEY` |
| VPS IP | 72.61.143.225 |
| Cloud URL (резерв) | https://leonidshvorob.app.n8n.cloud |
| Health check | https://n8n.srv1133622.hstgr.cloud/healthz |

---

## N8N REST API — все нужные эндпойнты

Документация: https://docs.n8n.io/api/api-reference/

Базовый URL: `https://n8n.srv1133622.hstgr.cloud/api/v1`
Заголовок: `X-N8N-API-KEY: <ключ>`

### Workflows

```
GET    /workflows                    — список всех воркфлоу (limit, active фильтры)
GET    /workflows/:id                — детали воркфлоу + все ноды
POST   /workflows                   — создать новый воркфлоу (JSON тело)
PUT    /workflows/:id                — полностью обновить воркфлоу
PATCH  /workflows/:id                — частично обновить (имя, ноды)
DELETE /workflows/:id                — удалить
POST   /workflows/:id/activate       — активировать (включить триггер)
POST   /workflows/:id/deactivate     — деактивировать
```

### Executions

```
GET    /executions                   — список запусков (limit, workflowId, status фильтры)
GET    /executions/:id               — детали конкретного запуска + данные нод
DELETE /executions/:id               — удалить запись о запуске
POST   /executions/run               — запустить воркфлоу вручную (workflowData + runData)
```

Статусы: `success`, `error`, `canceled`, `running`, `waiting`

### Credentials

```
GET    /credentials                  — список credentials (без секретов)
GET    /credentials/:id              — детали (без секретов)
POST   /credentials                  — создать новый
PUT    /credentials/:id              — обновить
DELETE /credentials/:id              — удалить
GET    /credentials/schema/:type     — схема для типа (напр. googleSheetsOAuth2Api)
```

### Tags & Misc

```
GET    /tags                         — список тегов
POST   /tags                         — создать тег
GET    /audit                        — аудит лог (активность пользователей)
GET    /variables                    — список variables (глобальные переменные)
POST   /variables                    — создать variable
```

### Webhook-запуск воркфлоу

```
POST   /webhook/:webhookPath         — production вебхук
POST   /webhook-test/:webhookPath    — test вебхук (не требует activation)
```

---

## Credentials — что уже настроено

| ID | Имя | Тип |
|---|---|---|
| isvTmT5STgsOYA7P | Google Sheets | googleSheetsOAuth2Api |
| GdhABHUNOrSdpf3A | Gmail | gmailOAuth2 |
| mKxHLRwJGD8dE7zc | Google Drive | googleDriveOAuth2Api |
| jw98MKRLXAx2TZFQ | Google Calendar | googleCalendarOAuth2Api |
| bhCwkWkygy01G6o4 | Google Docs | googleDocsOAuth2Api |
| xPd5QmuBRCTAZR05 | Google Slides | googleSlidesOAuth2Api |
| mcE7Ngmz366zNpPp | Google Service Account | googleApi |
| xRGMHOpI80jNdwOd | OpenAI | openAiApi |
| tl43n5Qde7Kp6f27 | Anthropic | anthropicApi |
| dGYPIsNxUMcF1m0m | Google Gemini | googlePalmApi |
| Qcnvgli2vMgSfRID | Groq | groqApi |
| friryNpPsfyYN26V | OpenRouter | openRouterApi |
| OSfMjhMmLFE9Crwq | Exa | exaApi |
| lIBrSBHhW46XelGZ | Exa account 2 | exaApi |
| k24I9Uu758YU55ky | Firecrawl | firecrawlApi |
| m4Q1fd0mD5chVB0o | Instantly (не используется) | instantlyApi |
| acNnuUo0GYIznhDn | Cal.com | calApi |
| VHLPVP3sUfwhnr3c | Apify (felix) | apifyApi |
| ayYl9wtKYLar9WGr | Apify (putu kadek) | apifyApi |
| c9KlXUg7wx8149pF | Postgres | postgres |
| ZfFlprO9onp2jYFi | VPS SSH root | sshPassword |
| ZgJS7J3PLut7Jfv7 | Slack | slackApi |
| RDEAEQdKXhQIJMbi | Slack 2 | slackApi |
| VUt8WwBZQhp1JBNP | Telegram (Soviet boots bot - не используется) | telegramApi |
| vDQx2LiI57utnUbI | Shopify | shopifyAccessTokenApi |

---

## Воркфлоу — текущий список (33 шт)

Теги расставлены через API. Фильтруй по тегу в левой панели N8N UI.

### FATHOM
| ID | Имя | Статус |
|---|---|---|
| 031gIgLPBlR0KbpM | Fathom -> Sales Calls Library | off |
| 0KnVjtGqOCMxtsNu | Fathom - get transcript | off |

### CAL
| ID | Имя | Статус |
|---|---|---|
| 17YGK6ErZ7TuZHxs | Nurture after meeting booked cal.com | ACTIVE |
| q4xY7Bcj0mVOGFN7 | Calcom - Booking manager | off |
| EYJ9EWYrRh9Mb59t | cal.com - nurture | off |

### PLUSVIBE
| ID | Имя | Статус |
|---|---|---|
| 4TXycOJQHSV0xAkn | PlusVibe - CRM Sync v3 | off |
| ohFOrowpQ5p57puL | PlusVibe - Follow-up Runner | off |
| bSHCxOvMmvBLY0fl | plusvibe - endpoints | off |
| 9iNzWy79oyLYE9pr | PlusVibe - autoresponder v2 (with schedule) | off |

### OUTREACH
| ID | Имя | Статус |
|---|---|---|
| gKLAY0RsqXHGAiAm | main pipeline | off |
| xOP4Sh9EHSuOW9mO | Positive reply - crm | off |
| cu4q1mk0k193WaqC | Email Copy - Saads strategy | off |

### UTIL
| ID | Имя | Статус |
|---|---|---|
| hKGKpXMhDG5qtwer | company name cleaner | off |
| xMGTzb8N7E8iJZwK | mailso + milverifieк - verify emails | off |
| NkDkPqgbGo7bo35a | verify emails mail.so | off |
| xGzS0aWx50345L7Q | exa ai website + summary | off |
| fTyzt4AEVzf8yJxe | icebreaker generator | off |
| nXWIuZv8wh02IczV | Outreach Daily Report v1 SSH Script | off |

### CLIENT-APS (теги: Client work + APS)
| ID | Имя | Статус |
|---|---|---|
| sownL4QlaIZ5o2cR | APS-Instagram Profile Scraper | off |
| gIGzgCZ2LLl2j8BW | apify - enrichment insta | off |

### ARCHIVE (13 воркфлоу — не трогать)
| ID | Имя | Причина |
|---|---|---|
| WlCUmbzViSdakuOy | vollna | эксперимент |
| ahbbnzujIWjiWV7w | Exmoor | эксперимент |
| Jkqh1ld35QePkiWO | shopify - abandoned | не используется |
| AzUhP4RhU7VpRwkR | My Sub-workflow | без имени/цели |
| iEVWZe9VYsdm4OMM | instantly test | тест, Instantly не используется |
| fYbGF5L7sBh4utzG | All Instantly Replies | Instantly не используется |
| qjCbUNOcuoTfZuW9 | PlusVibe - autoresponder v1 | заменен v2 |
| HZzHwbigfNEfAaDD | Plus vibe - autoreplie | дубль |
| ryFro2iHgk7MAx3A | PlusVibe - Simple Autoresponder | заменен v2 |
| wN2DXaieq3R9Gdek | Outreach Daily Report (дубль) | дубль с эмодзи |
| LAwU3IVpStpTb1w9 | firecrawl - website summary | заменен exa версией |
| 2YTHugslEcmMS7ee | website scraper + summary | старая утилита |
| 1Y5w9LyevMvdlw4o | rapid api - google search | эксперимент |

---

## Правила построения воркфлоу

### Именование

```
[КАТЕГОРИЯ] - [Триггер] - [Описание действия] - v[N]

Категории:
  LEAD      — обработка лидов, enrich, route
  OUTREACH  — отправка писем, follow-up, sequences
  SALES     — booking, nurture, CRM
  INTERNAL  — отчеты, утилиты, мониторинг
  DATA      — скрапинг, обогащение, очистка
  NOTIFY    — алерты в Slack/Telegram/Email
```

### Структура каждого воркфлоу

```
Trigger → [Validate input] → Main logic → [Error handler] → Notify
```

- Trigger: всегда явный (Webhook, Schedule, Manual, Cal, Gmail)
- Validate: Set нода с проверкой обязательных полей
- Error handler: подключать к финальной ноде через Error output
- Notify: Telegram или Slack при ошибке

### Code нода — только когда нет готовой

Есть нода → используй её:
- Instantly: `n8n-nodes-base.instantlyApi` — не HTTP Request
- Google Sheets: `n8n-nodes-base.googleSheets`
- Gmail: `n8n-nodes-base.gmail`
- Exa: `n8n-nodes-base.exaAi`
- Cal.com: `n8n-nodes-base.cal`
- Apify: `n8n-nodes-base.apify`

Code нода — только для трансформации данных.

### Sub-workflows для повторяющейся логики

Один раз написать, ссылаться через Execute Workflow нода:
- `UTIL - Enrich lead via Exa` — обогащение через Exa
- `UTIL - Verify email` — проверка email
- `UTIL - Send to Instantly` — добавить в кампанию
- `UTIL - Notify Telegram` — алерт

### StickyNote на каждый воркфлоу (обязательно)

```
## Что делает
[описание]

## Триггер
[webhook / schedule / manual]

## Credentials нужны
- Google Sheets (isvTmT5STgsOYA7P)
- Instantly (m4Q1fd0mD5chVB0o)

## Связанные воркфлоу
- [ID]: название
```

---

## Схема работы со мной (Claude Code)

1. Ты описываешь задачу словами
2. Я смотрю credentials выше → использую существующие ID
3. Строю JSON воркфлоу с нужными нодами
4. Деплою через `POST /api/v1/workflows`
5. Тестирую через `POST /executions/run` или webhook-test
6. Активирую через `POST /workflows/:id/activate`

---

## Гипотезы для максимального контроля

### H1: REST API (основа) — 80/20 выбор

**Покрывает:** создание, обновление, запуск, мониторинг воркфлоу
**Когда использовать:** всегда — это фундамент
**Статус:** работает сейчас

---

### H2: MCP сервер n8n — надстройка

**Что это:** n8n может выставить Claude инструменты через MCP протокол. Создаешь воркфлоу с нодой "MCP Server Trigger" — она становится инструментом Claude.

**Текущая проблема:** `settings.json` настроен на `/mcp-server/http`, но там возвращается HTML UI. Нужно создать воркфлоу с MCP Trigger нодой в самом n8n.

**Как починить:**
1. В n8n создать новый воркфлоу
2. Добавить ноду `MCP Server Trigger`
3. Добавить инструменты (Execute Workflow, Read Sheets, etc.)
4. URL тригера будет `https://n8n.srv1133622.hstgr.cloud/mcp/...`
5. Обновить URL в settings.json

Документация MCP в n8n: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger/

**Вывод по 80/20:** REST API даст 80% контроля без настройки. MCP добавит удобство (я смогу вызывать n8n инструменты в разговоре нативно), но это 20% усилий на 20% выигрыша. Делать после того как отработаем базовые паттерны.

---

### H3: Webhook мониторинг через Telegram

**Идея:** воркфлоу "INTERNAL - Error Monitor" — подписывается на все failed executions через polling и шлет в Telegram.

**Как:** Schedule trigger (каждые 30 мин) → `GET /executions?status=error&limit=10` → фильтр новых → Telegram notification

**Ценность:** узнаешь об ошибках сразу, не заходя в UI

---

### H4: SSH на VPS для глубокой диагностики

**Когда нужно:** n8n завис, нужен рестарт процесса, смотреть логи
**Credentials:** `ZfFlprO9onp2jYFi` (VPS SSH root) — уже настроен

```bash
# Логи n8n
journalctl -u n8n -f

# Рестарт
systemctl restart n8n

# Переменные окружения
cat /etc/n8n/.env
```

---

### H5: Postgres как хранилище состояния

**Идея:** использовать Postgres (credentials `c9KlXUg7wx8149pF`) как внешний стейт для воркфлоу.

**Примеры:**
- Дедупликация лидов (проверка "уже обработан?")
- История отправок
- Логи всех execution с деталями

Это важнее MCP — избавляет от дублей и дает историю.

---

## Итог: приоритеты по 80/20

| Приоритет | Инструмент | Ценность | Усилие |
|---|---|---|---|
| 1 | REST API | высокая | минимум (уже работает) |
| 2 | Telegram Error Monitor (H3) | высокая | 30 мин |
| 3 | Postgres как стейт (H5) | высокая | 1-2 ч |
| 4 | MCP сервер (H2) | средняя | 1 ч настройки |
| 5 | SSH диагностика (H4) | ситуационная | 0 (уже есть) |

**Вывод:** MCP не оверкил, но не первый приоритет. Начать с REST API + Telegram Monitor. MCP делать когда будет ощутимое неудобство без него.

---

## MX Provider Check — воркфлоу для лидов

Определяет email провайдера (Google, Microsoft, Other + шлюз) по домену.
Скрипт: `scripts/discovery/2026-03-30-mx-provider-final.py`

### Структура воркфлоу в n8n

```
Manual Trigger → Read Binary File → Code (parse CSV)
→ Split In Batches (50) → HTTP Request MX → HTTP Request TXT
→ Code (classify) → Aggregate → Code (build CSV) → Write Binary File
```

### HTTP Request MX (узел 4)
- Method: GET
- URL: `https://dns.google/resolve?name={{ $json["Email"].split("@")[1] }}&type=MX`
- Response: JSON

### HTTP Request TXT (узел 5)
- URL: `https://dns.google/resolve?name={{ $json["domain"] }}&type=TXT`

### Code — Classify (узел 6)

```js
const DIRECT = [
  { name: "Google",     patterns: ["aspmx.l.google.com","googlemail.com","alt1.aspmx","alt2.aspmx"] },
  { name: "Microsoft",  patterns: ["mail.protection.outlook.com","outlook.com"] },
  { name: "Mimecast",   patterns: ["mimecast.com"] },
  { name: "Proofpoint", patterns: ["pphosted.com"] },
  { name: "Barracuda",  patterns: ["barracudanetworks.com"] },
  { name: "Zoho",       patterns: ["zoho.com","zoho.eu"] },
  { name: "Yahoo",      patterns: ["yahoodns.net"] },
];

const GATEWAYS = {
  "hornetsecurity.com":  "Hornetsecurity",
  "ppe-hosted.com":      "Proofpoint Essentials",
  "sophos.com":          "Sophos",
  "trendmicro.com":      "Trend Micro",
  "zerospam.ca":         "ZeroSpam",
  "antispameurope.com":  "Antispam Europe",
  "mtaroutes.com":       "MTA Routes",
  "mxthunder.net":       "MX Thunder",
  "iphmx.com":           "Cisco IronPort",
  "arsmtp.com":          "AR SMTP",
  "emailservice.co":     "Email Service",
  "emailservice.io":     "Email Service",
  "emailservice.cc":     "Email Service",
  "siteprotect.com":     "SiteProtect",
  "mailhop.org":         "Mailhop",
  "titanhq.com":         "TitanHQ",
  "gosecure.net":        "GoSecure",
};

return $input.all().map(item => {
  const mxAns  = (item.json.mxResponse?.Answer  || []).filter(a => a.type === 15);
  const txtAns = (item.json.txtResponse?.Answer || []).filter(a => a.type === 16);

  const mxList = mxAns.map(a => a.data.split(" ").slice(1).join(" ").replace(/\.$/, "").toLowerCase());
  const txt    = txtAns.map(a => a.data).join(" ").toLowerCase();

  if (!mxList.length) return { json: { ...item.json, mx_provider: "No MX", mx_gateway: "" } };

  const combined = mxList.join(" ");
  for (const { name, patterns } of DIRECT) {
    if (patterns.some(p => combined.includes(p)))
      return { json: { ...item.json, mx_provider: name, mx_gateway: "" } };
  }

  const parts = mxList[0].split(".");
  const root  = parts.slice(-2).join(".");
  const gname = GATEWAYS[root] || root;
  const hint  = txt.includes("spf.protection.outlook.com") || txt.includes("onmicrosoft.com") ? "Microsoft"
              : txt.includes("_spf.google.com") ? "Google" : "";

  return { json: { ...item.json, mx_provider: "Other", mx_gateway: hint ? `${gname} (${hint})` : gname } };
});
```

### Добавить новый шлюз
В объект `GATEWAYS` добавить строку: `"newgateway.com": "Readable Name"`

### Результат
Две новые колонки в CSV:
- `mx_provider` — Google / Microsoft / Mimecast / Barracuda / Other / No MX
- `mx_gateway` — заполнено только если Other: `Hornetsecurity (Microsoft)`, `Sophos` и т.д.

---

## Полезные ссылки

- N8N API Reference: https://docs.n8n.io/api/api-reference/
- N8N Workflow JSON format: https://docs.n8n.io/workflows/export-import/
- N8N Built-in nodes list: https://docs.n8n.io/integrations/builtin/
- N8N Code node (JS): https://docs.n8n.io/code/code-node/
- N8N Sub-workflows: https://docs.n8n.io/flow-logic/subworkflows/
- N8N Error handling: https://docs.n8n.io/flow-logic/error-handling/
- N8N Expressions: https://docs.n8n.io/code/expressions/
- N8N MCP Trigger: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger/
- N8N Variables: https://docs.n8n.io/environments/variables/
- N8N Webhook node: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/

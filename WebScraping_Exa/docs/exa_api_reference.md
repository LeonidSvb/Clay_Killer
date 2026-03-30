# Exa AI API — Reference & Speed Guide

## Rate Limits

| Endpoint | Limit |
|----------|-------|
| `/search`, `/findSimilar` | 10 QPS |
| `/contents` | **100 QPS** |
| `/answer` | 10 QPS |

Для выхода за лимиты — enterprise план: hello@exa.ai

---

## Pricing

| Что | Цена |
|-----|------|
| Contents (страница) | $1 / 1k страниц |
| AI Summary | $1 / 1k страниц |
| Search | $7 / 1k запросов |

500 лидов с summary = ~$1 (500 страниц + 500 summary = $0.5 + $0.5)

---

## /contents — Все параметры

```json
{
  "ids": ["https://example.com"],

  "text": {
    "maxCharacters": 10000,
    "includeHtmlTags": false,
    "verbosity": "compact"
  },

  "summary": {
    "query": "Your custom prompt here",
    "schema": {}
  },

  "highlights": {
    "maxCharacters": 2000,
    "query": "What does this company do?"
  },

  "maxAgeHours": -1,
  "livecrawlTimeout": 10000,

  "subpages": 5,
  "subpage_target": ["about", "services", "solutions"]
}
```

---

## maxAgeHours — Главный параметр скорости

| Значение | Поведение |
|----------|-----------|
| `-1` | Только кэш, никогда не кроулит — **самый быстрый** |
| omitted | Баланс (дефолт) |
| `24` | Кэш если свежее 24ч, иначе кроулит |
| `1` | Кэш если свежее 1ч, иначе кроулит |
| `0` | Всегда живой краул — **самый медленный** |

**Для нашей задачи (summary лидов):** попробовать `maxAgeHours: -1` — если сайты есть в кэше Exa, будет значительно быстрее. Если нет в кэше — вернёт пустой результат.

> Старый параметр `livecrawl: "preferred"` — deprecated. Аналог: `maxAgeHours: 24`

---

## Subpages — Краул нескольких страниц

Для лучшего качества summary можно краулить не только главную но и подстраницы:

```json
{
  "ids": ["https://example.com"],
  "subpages": 5,
  "subpage_target": ["about", "services", "solutions", "who-we-serve"],
  "summary": { "query": "..." }
}
```

Каждая subpage = дополнительная страница по прайсу ($0.001).
Рекомендация Exa: начинать с 5-10 страниц.

**Это может дать лучшее качество summary** — главная страница часто не содержит всей инфы, а страница /about или /services — более конкретная.

---

## Варианты ускорения

### 1. maxAgeHours: -1 (только кэш)
Если сайты уже в индексе Exa — ответ мгновенный, нет краулинга.
Риск: если сайт не в кэше — вернёт пустой результат.

**Рекомендация:** сначала пробовать с `-1`, потом re-run с `omitted` для пустых результатов.

### 2. Убрать summary, взять только text
Summary — это отдельный LLM вызов на стороне Exa. Без него быстрее:
```json
{ "ids": [...], "text": { "maxCharacters": 3000 } }
```
Потом summary делаешь сам через OpenRouter (как в icebreaker workflow).
Но это усложняет пайплайн.

### 3. Enterprise rate limits
По умолчанию 100 QPS на /contents. На enterprise можно выше.
Но наш бенчмарк показал: ботленек не в rate limit а в скорости краулинга каждого сайта.
Enterprise не поможет если скорость ограничена самим вебом.

### 4. Highlights вместо Summary
`highlights` — быстрее чем `summary` (нет LLM генерации, только extraction):
```json
{ "ids": [...], "highlights": { "query": "What does this company do?", "maxCharacters": 1200 } }
```
Не генерирует текст, а вырезает релевантные куски из страницы. Быстрее, дешевле, но качество ниже.

---

## Наш бенчмарк (реальные данные, 100 URL)

### Без maxAgeHours (дефолт — живой краул)
| batch | concurrency | скорость | ~500 лидов |
|-------|-------------|----------|------------|
| 1 | 10 | 2.6/sec | ~194s |
| 1 | 20 | 2.8/sec | ~177s ← плато |
| 5 | 10 | 2.5/sec | ~198s |
| 30 | 10 | 2.3/sec | ~213s |

**Batch size не влияет вообще.**

### С maxAgeHours=24 (кэш + livecrawl fallback) ← ОПТИМУМ
| concurrency | скорость | ~500 лидов |
|-------------|----------|------------|
| 10 | 2.0/sec | 254s |
| 20 | 5.1/sec | 97s |
| **50** | **7.6/sec** | **~66s** |

**concurrency=50, maxAgeHours=24 → 500 лидов за ~66 сек** (vs n8n 210 сек = 3x быстрее)
92/100 ok, 8 ошибок — сайты которых нет в кэше и таймаутят при живом краулинге.

### Итог
- Ботленек был в отсутствии кэша — Exa кроулил каждый сайт заново
- maxAgeHours=24 позволяет брать из кэша и даёт 3x прирост
- Оптимальный конфиг: `batch=1, concurrency=50, maxAgeHours=24`

---

## Что стоит протестировать

1. `maxAgeHours: -1` — если сайты в кэше, может дать 2-5x ускорение
2. `subpages: 3-5` с `subpage_target: ["about", "services"]` — лучше качество summary
3. `highlights` вместо `summary` — быстрее, но другое качество
4. Two-pass: сначала `-1` (кэш), потом второй прогон для тех у кого пустой результат

---

## SDK

```python
pip install exa-py
```

```python
from exa_py import Exa
exa = Exa(api_key="...")
result = exa.get_contents(["https://example.com"], summary={"query": "..."})
```

---

## Полезные ссылки

- Docs: https://docs.exa.ai
- Dashboard / API Keys: https://dashboard.exa.ai/api-keys
- Pricing: https://exa.ai/pricing
- Enterprise: hello@exa.ai
- Rate limits: https://docs.exa.ai/reference/rate-limits

---
id: "TASK-001"
title: "core/prescreener.py — URL classifier (html_light / js_heavy / blocked / dead)"
status: "planned"
priority: "P0"
labels: ["core", "scraping", "foundation"]
dependencies: []
created: "2026-03-30"
---

# 1) High-Level Objective

Написать `core/prescreener.py` — быстрый async классификатор URL.
Делает HTTP GET первых 10KB каждого сайта и определяет:
html_light / js_heavy / blocked / dead

Это Pass 0 в pipeline. Бесплатно. ~60 сек на 5000 URL.
Результат определяет маршрутизацию: scraper vs Exa.

# 2) Background / Context

Тест-файл: C:\Users\79818\Downloads\314e74cc-a937-4c17-bb4c-0b24e0d499a8.csv
URL колонка: company_website
535 строк, Staffing & Recruiting индустрия, международные компании.

Ожидаемое распределение на реальных B2B сайтах:
  html_light: ~50-60% (WordPress, Squarespace, static HTML)
  js_heavy:   ~25-30% (React, Next.js, Vue, Angular)
  blocked:    ~10-15% (Cloudflare, 403/503)
  dead:       ~5%     (DNS fail, timeout)

# 3) Assumptions & Constraints

- ASSUMPTION: достаточно первых 10KB HTML для классификации
- ASSUMPTION: timeout 8 сек достаточен для живых сайтов
- Constraint: не скачивать весь HTML — только первые 10KB (параметр max_bytes)
- Constraint: concurrency=100 (не более, чтобы не получить бан)
- Constraint: User-Agent должен быть реалистичным браузерным

# 4) Dependencies

- .env (EXA_API_KEY не нужен для этого модуля)
- requirements.txt: aiohttp, python-dotenv

# 5) Context Plan

**Beginning:**
- docs/PRD.txt _(read-only)_
- C:\Users\79818\Downloads\314e74cc-a937-4c17-bb4c-0b24e0d499a8.csv _(read-only)_

**End state:**
- core/__init__.py
- core/prescreener.py
- (тест запускается inline, файл не создаётся)

# 6) Low-Level Steps

1. **Создать core/__init__.py** (пустой)
   - File: `core/__init__.py`

2. **Написать core/prescreener.py**
   - File: `core/prescreener.py`

   Типы:
   ```python
   SiteClass = Literal["html_light", "js_heavy", "blocked", "dead"]

   @dataclass
   class ScreenResult:
       url: str
       site_class: SiteClass
       text_length: int        # chars реального текста найденного в body
       reason: str             # почему такая классификация
       elapsed_ms: int
   ```

   Публичный API:
   ```python
   async def screen_url(
       session: aiohttp.ClientSession,
       sem: asyncio.Semaphore,
       url: str,
       timeout: int = 8,
       max_bytes: int = 10_000,
   ) -> ScreenResult: ...

   async def screen_batch(
       urls: list[str],
       concurrency: int = 100,
       timeout: int = 8,
   ) -> list[ScreenResult]: ...
   ```

3. **Логика классификации в screen_url:**

   DEAD если:
   - aiohttp.ClientConnectorError (DNS fail)
   - asyncio.TimeoutError
   - любой Exception при коннекте

   BLOCKED если:
   - HTTP status 403, 503
   - "cf-ray" в response headers (Cloudflare)
   - "Just a moment" или "Enable JavaScript" в первых 10KB

   JS_HEAVY если (проверять в порядке):
   - body содержит: '<div id="root"></div>', '<div id="app"></div>'
   - body содержит: 'window.__NEXT_DATA__', 'window.__NUXT__', 'ng-version='
   - body содержит: '__REACT_APP', 'data-reactroot'
   - реальный текст после strip тегов < 300 chars И body < 3000 chars

   HTML_LIGHT если:
   - HTTP status 200
   - реальный текст >= 300 chars
   - нет JS-фреймворк сигнатур

   "Реальный текст" = body без script/style/nav/footer тегов,
   только visible text content.

4. **User-Agent:**
   ```python
   HEADERS = {
       "User-Agent": (
           "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/122.0.0.0 Safari/537.36"
       ),
       "Accept": "text/html,application/xhtml+xml",
       "Accept-Language": "en-US,en;q=0.9",
   }
   ```

5. **CLI точка для тестирования (в конце файла, if __name__ == "__main__"):**
   ```
   py core/prescreener.py --input path/to/file.csv --col company_website --limit 100
   ```
   Выводит:
   - распределение по классам (count + %)
   - время выполнения
   - примеры URL каждого класса (по 3 штуки)
   - скорость (URL/sec)

# 7) Types

```python
from dataclasses import dataclass
from typing import Literal

SiteClass = Literal["html_light", "js_heavy", "blocked", "dead"]

@dataclass
class ScreenResult:
    url: str
    site_class: SiteClass
    text_length: int
    reason: str
    elapsed_ms: int
```

# 8) Acceptance Criteria

- `from core.prescreener import screen_batch` работает без ошибок
- На 100 URL из тест-файла завершается за < 30 сек
- Возвращает ScreenResult для каждого URL (нет пропущенных)
- dead URLs не крашат скрипт
- CLI вывод показывает распределение классов

# 9) Testing Strategy

- Запустить inline на 50 URL из тест-файла
- Проверить вручную 3-5 результатов из каждого класса (открыть сайт, убедиться что классификация верная)
- Проверить что мёртвые домены возвращают SiteClass="dead" без exception
- Замерить скорость: должно быть > 20 URL/sec при concurrency=100

# 10) Notes

- beautifulsoup4 нужен только для извлечения visible text при классификации
- НЕ использовать Playwright/Selenium — только aiohttp
- Cloudflare часто возвращает 200 но с challenge page — детектировать по тексту
- Некоторые сайты редиректят http → https, aiohttp follow_redirects=True

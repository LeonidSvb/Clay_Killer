---
id: "TASK-002"
title: "core/scraper.py — BeautifulSoup scraper для html_light сайтов"
status: "planned"
priority: "P0"
labels: ["core", "scraping"]
dependencies: ["TASK-001"]
created: "2026-03-30"
---

# 1) High-Level Objective

Написать `core/scraper.py` — async scraper для сайтов класса html_light.
Скачивает homepage + опционально subpages через обычный HTTP (бесплатно).
Возвращает чистый текст без мусора (nav/footer/script/style).

# 2) Background / Context

Используется только для html_light сайтов из TASK-001.
Для js_heavy и blocked — Exa (TASK-003).

Экономика: html_light ~50% от 5000 лидов = 2500 сайтов.
При $0.001/page через Exa это экономия $2.50 на 5000 лидов.
Главная ценность — скорость и контроль над текстом.

# 3) Assumptions & Constraints

- Constraint: только HTTP GET, никаких браузеров
- Constraint: subpages только с того же домена (no external links)
- Constraint: max 5 subpages (настраиваемо)
- ASSUMPTION: если scraper вернул < 300 chars текста → fallback to Exa

# 4) Dependencies

- core/prescreener.py (TASK-001) — для SiteClass типа
- requirements.txt: aiohttp, beautifulsoup4, lxml

# 5) Context Plan

**Beginning:**
- core/prescreener.py _(read-only)_
- docs/PRD.txt _(read-only)_

**End state:**
- core/scraper.py

# 6) Low-Level Steps

1. **Типы:**
   ```python
   @dataclass
   class PageContent:
       url: str
       text: str           # очищенный текст
       char_count: int
       source: str         # "scraper" | "exa"

   @dataclass
   class ScrapeResult:
       url: str
       pages: list[PageContent]   # homepage + subpages
       total_text: str            # конкатенация всех страниц
       total_chars: int
       ok: bool
       error: str | None
   ```

2. **Функция очистки HTML:**
   ```python
   def extract_text(html: str) -> str:
   ```
   - BeautifulSoup с lxml парсером
   - Удалить теги: script, style, nav, footer, header, aside, form, iframe, noscript
   - Удалить атрибуты: class, id, style, onclick (оставить href для subpage discovery)
   - get_text(separator=" ", strip=True)
   - Нормализовать пробелы (re.sub whitespace)
   - Вернуть строку

3. **Функция discovery subpages:**
   ```python
   def discover_subpages(html: str, base_url: str, targets: list[str]) -> list[str]:
   ```
   - Найти все <a href> ссылки
   - Оставить только тот же домен
   - Приоритизировать ссылки у которых href содержит слова из targets
   - Убрать: #anchors, ?query params, .pdf/.jpg/.png
   - Дедупликация
   - Вернуть топ N URL

4. **Публичный API:**
   ```python
   async def scrape_url(
       session: aiohttp.ClientSession,
       sem: asyncio.Semaphore,
       url: str,
       subpages: int = 0,
       subpage_targets: list[str] = None,
       min_text_length: int = 300,
       timeout: int = 10,
   ) -> ScrapeResult: ...

   async def scrape_batch(
       urls: list[str],
       concurrency: int = 50,
       subpages: int = 0,
       subpage_targets: list[str] = None,
       min_text_length: int = 300,
   ) -> list[ScrapeResult]: ...
   ```

   Дефолтный subpage_targets:
   ["about", "services", "solutions", "clients", "industries", "who-we-serve", "what-we-do"]

5. **Fallback логика в scrape_url:**
   - Если итоговый total_chars < min_text_length → ok=False, error="insufficient_text"
   - Pipeline потом отправит этот URL в Exa

6. **CLI для тестирования:**
   ```
   py core/scraper.py --input file.csv --col company_website --limit 20 --subpages 3
   ```
   Выводит для каждого URL:
   - статус ok/fail
   - количество страниц
   - total chars
   - превью первых 200 chars текста

# 8) Acceptance Criteria

- `from core.scraper import scrape_batch` работает
- На 20 html_light URL возвращает текст > 300 chars для большинства
- Subpage discovery находит /about, /services типа страницы
- Сайты которые вернули < 300 chars имеют ok=False
- Никаких навигационных элементов в тексте (проверить вручную)

# 9) Testing Strategy

- Взять 20 URL из prescreener результата класса html_light
- Запустить с subpages=3
- Открыть 3-5 сайтов вручную, сравнить текст
- Убедиться что /about страница была найдена если существует

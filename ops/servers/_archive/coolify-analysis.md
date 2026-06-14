# Coolify — анализ под твой сервак
Дата: 2026-06-08
Сервер: 152.53.194.162 (netcup VPS 1000 G12, Debian 13)

---

## Что такое Coolify по первичным принципам

Coolify — это веб-UI поверх Docker, который делает то что ты сейчас делаешь руками:
- пишешь docker-compose файлы в /opt/compose/
- настраиваешь nginx конфиги вручную
- деплоишь через SSH + `docker compose up`

Coolify заменяет всё это браузерным интерфейсом + автодеплоем из GitHub.

### Под капотом:

```
GitHub push
    ↓
Coolify (Laravel + PHP, порт 8000)
    ↓
Docker API (создаёт/обновляет контейнеры)
    ↓
Traefik (reverse proxy, заменяет nginx)
    ↓
Let's Encrypt (SSL, заменяет certbot)
    ↓
Твои приложения
```

**Ключевые компоненты Coolify на сервере:**
- `coolify` — сам UI (Laravel, порт 8000)
- `coolify-proxy` — Traefik контейнер (порты 80/443)
- `coolify-db` — PostgreSQL для хранения состояния Coolify
- `coolify-redis` — очередь задач

**REST API:** да, полноценный. Можно триггерить деплои, управлять сервисами, получать статусы — всё программно.

---

## Твой текущий стек vs Coolify

| Сервис | Текущее расположение | В Coolify |
|---|---|---|
| n8n | /opt/compose/n8n/ | Управляется через UI, автодеплой из GitHub |
| Uptime Kuma | /opt/compose/uptime-kuma/ | One-click service в UI |
| Supabase (minimal) | /opt/compose/supabase/ | Кастомный compose — можно импортировать |
| Metabase | /opt/compose/metabase/ | One-click service в UI |
| Email Verifier | /opt/apps/email-verifier/ | Deploy из GitHub + build config |
| nginx | /etc/nginx/ | ЗАМЕНЯЕТСЯ на Traefik |
| PV-sync | /opt/apps/projects/ | Deploy из GitHub, cron через Coolify |
| skool-scrape-signals | /opt/apps/projects/ | Deploy из GitHub |
| tg-monitoring | /opt/apps/projects/ | Deploy из GitHub |
| fanfic-gen | /opt/apps/projects/ | Deploy из GitHub |
| PostgreSQL (хостовый) | localhost:5432 | НЕ трогается — Coolify его не видит |

---

## КОНФЛИКТЫ — критически важно прочитать

### Конфликт 1: порт 8000 (БЛОКЕР)
- Coolify UI по умолчанию запускается на порту 8000
- Твой Supabase Studio тоже на порту 8000
- **Оба не запустятся одновременно**
- Решение: Coolify UI переносится на другой порт (например 3333) через env var `APP_PORT`

### Конфликт 2: nginx → Traefik
- Coolify использует Traefik вместо nginx
- У тебя nginx настроен с Cloudflare + self-signed cert для n8n.pamelacoreypc.com
- При установке Coolify нужно выбрать: либо Coolify управляет прокси (Traefik), либо "Coolify behind existing proxy"
- Рекомендую: оставить nginx, поставить Coolify в режим "no proxy management"
- Тогда nginx остаётся, Traefik не поднимается, ты сам добавляешь nginx локейшены

### Конфликт 3: существующие docker-compose стеки
- Coolify берёт под управление Docker networking
- Твои существующие стеки в /opt/compose/ он НЕ обнаруживает автоматически
- Нужно мигрировать каждый стек вручную через UI
- Или: оставить старые стеки как есть, новые запускать через Coolify

### Конфликт 4: Supabase кастомная конфигурация
- У тебя minimal Supabase с пропатченным kong.yml и убранными 10 сервисами
- Coolify's one-click Supabase — это полный стек (~15 контейнеров), не совпадёт
- Нужно импортировать твой кастомный docker-compose через "Docker Compose" тип деплоя
- Все переменные из .env нужно перенести в Coolify UI вручную

---

## Что Coolify реально даёт тебе

### Плюсы:
1. **Автодеплой из GitHub** — для PV-sync, tg-monitoring, fanfic-gen это очень удобно. Пушишь → деплоится автоматически. Сейчас у тебя это либо вручную, либо через GitHub Actions.

2. **Env vars через UI** — не лезешь в SSH чтобы поменять переменную. Меняешь в браузере → рестарт контейнера автоматически.

3. **Логи в реальном времени** — видишь логи всех контейнеров в браузере без SSH.

4. **Один дашборд** — всё в одном месте: статус контейнеров, деплои, логи, env vars.

5. **SSL автоматически** — Let's Encrypt без certbot-танцев. Добавил домен → сертификат появился.

6. **Cron для скриптов** — PV-sync, skool-scrape-signals можно запускать по расписанию через Coolify без system cron.

7. **API** — можно триггерить деплои из n8n воркфлоу. Например: n8n workflow → POST /api/v1/deploy → перезапустить сервис.

### Минусы:
1. **Ещё один слой абстракции** — если Coolify сломался, ты не знаешь что происходит с контейнерами.

2. **Занимает ресурсы** — сам Coolify + Traefik + его PostgreSQL + Redis = ~300-500MB RAM постоянно.

3. **Кривая миграция с nginx** — Cloudflare + nginx + self-signed уже работает. Трогать это рискованно.

4. **Supabase migration боль** — придётся вручную переносить кастомный compose + все env vars.

5. **Uptime Kuma дублирует часть функций** — у Coolify есть базовый мониторинг, Uptime Kuma мощнее. Они не конфликтуют, но пересекаются.

---

## Оценка боли миграции по каждому сервису

| Сервис | Боль | Что делать |
|---|---|---|
| Uptime Kuma | Низкая | Пересоздать через Coolify one-click, данные в volume |
| Metabase | Низкая | Пересоздать, подключить к 127.0.0.1:5434 через внешнюю сеть |
| n8n | Средняя | Volumes с данными перенести, env vars перенести, nginx конфиг обновить |
| Email Verifier | Средняя | Настроить build + env в Coolify UI, проверить что localhost:8090 доступен |
| PV-sync / tg-monitor / fanfic-gen | Низкая | Подключить GitHub репо → автодеплой |
| skool-scrape-signals | Средняя | Нет git history, нужно сначала в GitHub |
| Supabase | Высокая | Импорт кастомного compose, перенос всех секретов из .env, риск потери данных |
| PostgreSQL хостовый | Нет | Не трогать — вне Docker, Coolify его не трогает |
| nginx + Cloudflare | Высокая | Либо оставить nginx, либо мигрировать на Traefik + перенастроить Cloudflare |

---

## Рекомендация: стоит ли мигрировать?

**Короткий ответ: не сейчас, не всё.**

**Что реально имеет смысл:**
- Новые проекты (Apify акторы, новые скрипты) — сразу деплоить через Coolify
- PV-sync, tg-monitoring, fanfic-gen — несложная миграция, получишь автодеплой из GitHub

**Что НЕ трогать:**
- nginx + Cloudflare + n8n — работает, не ломай
- Supabase — слишком кастомный, миграция рискованная
- PostgreSQL хостовый — он вообще вне Docker

**Оптимальный сценарий:**
1. Поставить Coolify с `APP_PORT=3333` (избежать конфликт с портом 8000)
2. Запустить в режиме "без proxy management" (сохранить nginx)
3. Мигрировать только лёгкие проекты: PV-sync, tg-monitoring, fanfic-gen
4. Новые сервисы сразу через Coolify
5. Supabase / n8n / nginx — не трогать

---

## Установка (если решишь попробовать)

```bash
# на сервере
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash

# после установки — сменить порт в /data/coolify/.env
APP_PORT=3333

# запустить в режиме без proxy
# в UI: Settings → Proxy → "None / Use existing proxy"
```

Coolify открывается по http://152.53.194.162:3333
Порт 3333 открыть в UFW: `ufw allow 3333/tcp`

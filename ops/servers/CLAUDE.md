# Server Ops — netcup-primary

## Быстрый контекст

Сервер Netcup VPS ARM64, 8GB RAM, 256GB NVMe. IP: 152.53.194.162
Все credentials и команды: `netcup-primary.env`
Все ссылки и туннели: `access.md`
Текущий план работ: `TODO.txt`
Отдельный план по n8n: `TODO.n8n.txt`

## Что задеплоено

- **n8n** — /opt/compose/n8n/, http://152.53.194.162/n8n/
- **Uptime Kuma** — /opt/compose/uptime-kuma/, http://152.53.194.162:3001
- **Supabase** — /opt/compose/supabase/, http://152.53.194.162:8000
- **sync-data** — /opt/apps/projects/sync-data/ — все джобы синка данных (PlusVibe API + Cal.com + notifications); cron: */30 all, 01:00 daily_stats, */6h calcom; лог sync.log в папке проекта

## n8n — важный контекст

- Актуальный публичный URL: `https://n8n.pamelacoreypc.com/`
- Старый IP-URL `http://152.53.194.162/n8n/` больше не основной путь доступа
- Контейнер n8n слушает `127.0.0.1:5678`, наружу порт `5678` не открыт
- `n8n` переведён на root-path `/`, не на `/n8n/`
- В `.env` сейчас:
  - `N8N_HOST=n8n.pamelacoreypc.com`
  - `N8N_PROTOCOL=https`
  - `N8N_PORT=5678`
  - `N8N_PATH=/`
  - `WEBHOOK_URL=https://n8n.pamelacoreypc.com/`
  - `N8N_EDITOR_BASE_URL=https://n8n.pamelacoreypc.com/`
  - `N8N_SECURE_COOKIE=true`
- В nginx:
  - `80` и `443` обслуживают `n8n.pamelacoreypc.com`
  - proxy идёт на `http://127.0.0.1:5678`
  - для `443` в proxy header жёстко передаётся `X-Forwarded-Proto https`
- На origin поднят self-signed TLS сертификат для `n8n.pamelacoreypc.com`, чтобы Cloudflare перестал отдавать `521`
- `certbot` и `python3-certbot-nginx` установлены, но автоматический выпуск Let's Encrypt в этой сессии упал с ACME ошибкой `No such authorization`
- Owner account в `n8n` уже создан и вход подтверждён
- После фикса проверено:
  - публичный `https://n8n.pamelacoreypc.com/` -> `200`
  - origin `https://127.0.0.1/` с `Host: n8n.pamelacoreypc.com` -> `200`

## Supabase — архитектурные решения

Минимальный стек: `db + auth + rest + meta + studio + kong`

Намеренно убрано (не менять без причины):
- `analytics` (logflare) — memory leak до 1.8GB
- `realtime` — не используется
- `storage` — файлы хранятся в Google Drive
- `edge-functions`, `imgproxy`, `vector`, `supavisor` — не нужны

Supabase PostgreSQL — отдельный контейнер, **не связан** с хостовым PostgreSQL.
Хостовый PostgreSQL (порт 5432) не трогать — там icegen, leads, outreach, metabase.

## SSH

```
ssh -i ~/.ssh/id_ed25519_hostinger leonid@152.53.194.162
```

sudo пароль — в netcup-primary.env (SERVER_ADMIN_PASSWORD)

## Что ещё не сделано

См. TODO.txt: Phase 4 (миграция данных), Phase 5 (бэкап), Phase 6 (скрипты), Phase 7 (Metabase)

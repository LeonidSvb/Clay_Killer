# Server Ops — netcup-primary

## Быстрый контекст

Сервер Netcup VPS ARM64, 8GB RAM, 256GB NVMe. IP: 152.53.194.162
Все credentials и команды: `netcup-primary.env`
Все ссылки и туннели: `access.md`
Текущий статус задач: `TODO.txt`

## Что задеплоено

- **Traefik** — /data/coolify/proxy/ (root-owned), слушает 80/443, SSL via Cloudflare DNS Challenge
- **Coolify** — порт 8000, UI через SSH-туннель
- **n8n** — /opt/compose/n8n/, https://n8n.pamelacoreypc.com/
- **Uptime Kuma** — /opt/compose/uptime-kuma/, https://uptime.pamelacoreypc.com/
- **Outreach Cockpit** — /opt/apps/outreach-cockpit/, https://cockpit.pamelacoreypc.com/
- **Supabase** — /opt/compose/supabase/, Studio через SSH-туннель порт 8001
- **Email Verifier** — /opt/apps/email-verifier/, порт 8090 (localhost only)
- **sync-data** — /opt/apps/projects/sync-data/, cron: */30 all, 01:00 daily_stats, */6h calcom, 12:00 revenue
- **shared-postgres** — docker контейнер, порт 5432 (127.0.0.1), user: app_admin

## Traefik — важный контекст

- nginx **отключён** (sudo systemctl disable nginx)
- Traefik слушает 80/443, SSL через Let's Encrypt DNS Challenge (Cloudflare)
- Compose файл: /data/coolify/proxy/docker-compose.yml (root-owned — редактировать через base64+sudo)
- Динамические конфиги: /data/coolify/proxy/dynamic/ (n8n.yml, cockpit.yml, uptime.yml)
- Traefik подключён к сетям: coolify, n8n_default, outreach-cockpit_cockpit-net, uptime-kuma_default
- Чтобы добавить новый домен: создать YAML в dynamic/, подключить сеть через docker network connect

## n8n — важный контекст

- URL: https://n8n.pamelacoreypc.com/
- Контейнер слушает 127.0.0.1:5678 (не открыт наружу)
- N8N_PATH=/, N8N_HOST=n8n.pamelacoreypc.com, N8N_SECURE_COOKIE=true
- Traefik маршрутизирует через n8n_default docker network (контейнер n8n-app)

## Supabase — архитектурные решения

Минимальный стек: db + auth + rest + meta + studio + kong (порт 8001 на хосте)

Намеренно убрано (не менять без причины):
- analytics (logflare) — memory leak до 1.8GB
- realtime, storage, edge-functions, imgproxy, vector, supavisor — не нужны

Supabase PostgreSQL — отдельный контейнер (supabase-db), порт 5434.
Хостовый shared-postgres — отдельный контейнер, user: app_admin, базы: icegen, outreach_sync, platform, tg_monitoring.

## Backup

- Скрипт: /opt/backups/backup.sh
- Cron: 0 3 * * * (ежедневно 03:00)
- Google Drive: gdrive:server-backups/
- Дампит: host-postgres, supabase-postgres, n8n-postgres, compose files

## SSH

```
ssh -i ~/.ssh/id_ed25519_hostinger leonid@152.53.194.162
```

sudo пароль — в netcup-primary.env (SERVER_ADMIN_PASSWORD)

## Что ещё не сделано

- Упtime Kuma мониторы (вручную через UI)
- Metabase (поднять когда нужно)
- Email Verifier доработки (см. TODO.txt)

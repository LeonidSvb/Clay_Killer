SERVER STATUS — netcup-primary
================================
Последнее обновление: 2026-06-14
IP: 152.53.194.162


СЕРВИСЫ (запущены)
-------------------

| Сервис          | Тип          | URL / Порт                                | Путь на сервере                      |
|-----------------|--------------|-------------------------------------------|--------------------------------------|
| Traefik         | docker        | :80 / :443                                | /data/coolify/proxy/                 |
| Coolify         | docker        | https://coolify.pamelacoreypc.com/        | /data/coolify/source/                |
| n8n             | docker compose| https://n8n.pamelacoreypc.com/            | /opt/compose/n8n/                    |
| Uptime Kuma     | docker compose| https://uptime.pamelacoreypc.com/         | /opt/compose/uptime-kuma/            |
| Outreach Cockpit| docker compose| https://cockpit.pamelacoreypc.com/        | /opt/apps/outreach-cockpit/          |
| Supabase stack  | docker compose| Studio: SSH tunnel :8001                  | /opt/compose/supabase/               |
| Email Verifier  | docker        | localhost:8090 (внутри n8n: 172.20.0.1)   | /opt/apps/email-verifier/            |
| Signal Tracker  | systemd       | https://philippe.pamelacoreypc.com/       | /opt/apps/signal-tracker/ (:3099)    |
| shared-postgres | docker        | 127.0.0.1:5432 (user: app_admin)          | docker run напрямую                  |

Supabase контейнеры: db, auth, rest, meta, studio, kong
Намеренно убрано: analytics, realtime, storage, edge-functions, imgproxy, vector, supavisor


СЕРВИСЫ (на паузе / не нужны сейчас)
--------------------------------------
- Metabase      — compose: /opt/compose/metabase/ — убит (1.7GB RAM), данные в Supabase metabase schema
- NocoDB        — база есть в shared-postgres, сервис не поднят (Supabase Studio заменяет)
- fanfic-gen    — /opt/apps/projects/fanfic-gen/ — заброшен


БАЗЫ ДАННЫХ
------------

shared-postgres (docker, host port 5432, user: app_admin):
  - icegen
  - leads
  - nocodb
  - outreach       ← outreach воркфлоу, синхронизируется через sync-data

supabase-db (docker, host port 5434, user: postgres):
  - public schema — auth, supabase системные таблицы
  - outreach schema — основные таблицы outreach (лиды, обогащение)
  - enrichment schema — обогащённые данные
  - metabase schema — данные Metabase (парковка)

n8n-postgres (docker internal, только для n8n):
  - n8n воркфлоу, credentials, execution history


ПРОЕКТЫ НА СЕРВЕРЕ (/opt/apps/projects/)
-----------------------------------------

| Проект               | GitHub                           | Путь на сервере                              |
|----------------------|----------------------------------|----------------------------------------------|
| sync-data            | LeonidSvb/sync-data              | /opt/apps/projects/sync-data/                |
| tg-monitoring        | LeonidSvb/tg-monitoring          | /opt/apps/projects/tg-monitoring/            |
| skool-scrape-signals | LeonidSvb/skool-scrape-signals   | /opt/apps/projects/skool-scrape-signals/     |
| PV-sync              | LeonidSvb/pv-sync                | /opt/apps/projects/PV-sync-hack-airtable/    |

PV-sync — отключён, заменён sync-data.


CRON JOBS (пользователь leonid)
--------------------------------
*/30 * * * *   sync-data — основная синхронизация outreach
0 1 * * *      sync-data — daily_stats
0 */6 * * *    sync-data — calcom sync
0 12 * * *     sync-data — revenue
0 6 * * *      tg-monitoring — daily-report.py
0 7 * * *      skool-scrape-signals — run.py
0 8 * * *      skool-scrape-signals — daily_report.py
0 3 * * *      /opt/backups/backup.sh (root cron)

Лог sync-data: /opt/apps/projects/sync-data/sync.log


БЭКАП
------
Скрипт: /opt/backups/backup.sh | Cron: 03:00 ежедневно
Что дампится: host-postgres, supabase-postgres, n8n-postgres, compose файлы
Куда: gdrive:server-backups/ (rclone)
Локальные файлы: удаляются через 7 дней
Последний успешный тест: 2026-06-08


МОНИТОРИНГ
-----------
Uptime Kuma: https://uptime.pamelacoreypc.com/
Логин: leonid / (в netcup-primary.env → UPTIME_KUMA_PASSWORD)
Статус: РАБОТАЕТ, мониторы ещё не настроены вручную (см. backlog.md)

SERVER STATUS — netcup-primary
================================
Последнее обновление: 2026-06-15
IP: 152.53.194.162


КАК ЗАДЕПЛОИТЬ НОВЫЙ ПРОЕКТ НА COOLIFY (5 минут)
--------------------------------------------------
1. Создать GitHub репо (публичное или приватное — оба работают)
2. Убедиться что в репо есть Dockerfile или docker-compose.yml
3. API: создать проект → создать app → передеплоить → добавить env vars
   BASE="https://coolify.pamelacoreypc.com/api/v1"
   TOKEN="4|372d39f982cce5da69af085522ff5bc5ff83e5fb1f46d901c62bc79c332b6ee1"
   SERVER="i31qr902vudauxh8yayi9wsu"
   KEY="u14n00ocxxff9mmvjo8kpdtb"  ← SSH ключ Coolify (добавлен в GitHub на уровне аккаунта)

   # Приватный репо (Dockerfile):
   curl -s -X POST "$BASE/projects" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"name":"PROJECT","description":"..."}'  # → получаем project_uuid

   curl -s -X POST "$BASE/applications/private-deploy-key" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"project_uuid":"...","server_uuid":"'$SERVER'","environment_name":"production",
          "git_repository":"git@github.com:LeonidSvb/REPO.git","git_branch":"main",
          "build_pack":"dockerfile","name":"NAME","domains":"https://SUBDOMAIN.pamelacoreypc.com",
          "ports_exposes":"3000","private_key_uuid":"'$KEY'","instant_deploy":false}'  # → app_uuid

   curl -s "$BASE/deploy?uuid=APP_UUID&force=false" -H "Authorization: Bearer $TOKEN"

   # Публичный репо:
   # Тот же запрос но endpoint /applications/public, git_repository через https://, без private_key_uuid

4. GitHub Webhook для авто-деплоя при push:
   Репо → Settings → Webhooks → Add webhook
   URL: https://coolify.pamelacoreypc.com/webhooks/source/github/events/manual?token=WEBHOOK_TOKEN
   Content-type: application/json | Secret: ТОТ ЖЕ WEBHOOK_TOKEN | Just the push event
   ВАЖНО: secret обязателен — Coolify проверяет HMAC-подпись, без secret деплой не сработает!
   Webhook token: curl "$BASE/applications/APP_UUID" -H "Authorization: Bearer $TOKEN" | jq .manual_webhook_secret_github

5. Добавить Cloudflare DNS (если новый субдомен):
   curl -s -X POST "https://api.cloudflare.com/client/v4/zones/95b3bb83d3f4c5bd677b016bd8d1c287/dns_records" \
     -H "X-Auth-Email: leo@systemhustle.com" -H "X-Auth-Key: $CLOUDFLARE_API_KEY" \
     -H "Content-Type: application/json" \
     --data '{"type":"A","name":"SUBDOMAIN","content":"152.53.194.162","ttl":1,"proxied":true}'

ВАЖНО — env vars в Coolify:
  - NEXT_PUBLIC_* переменные → is_buildtime: true (передаются как Docker build args → нужны ARG в Dockerfile!)
  - Рантайм переменные → is_buildtime: false
  - docker-compose buildpack ищет файл docker-compose.yml (не .yaml!) → патч: docker_compose_location: "/docker-compose.yml"


СЕРВИСЫ (запущены)
-------------------

| Сервис          | Управление    | URL / Порт                                | GitHub / Путь                        |
|-----------------|---------------|-------------------------------------------|--------------------------------------|
| Traefik         | вне Coolify   | :80 / :443                                | /data/coolify/proxy/                 |
| Coolify         | docker        | https://coolify.pamelacoreypc.com/        | /data/coolify/source/                |
| n8n             | вне Coolify   | https://n8n.pamelacoreypc.com/            | /opt/compose/n8n/                    |
| Uptime Kuma     | вне Coolify   | https://uptime.pamelacoreypc.com/         | /opt/compose/uptime-kuma/            |
| Outreach Cockpit| Coolify ✓     | https://cockpit.pamelacoreypc.com/        | LeonidSvb/outreach-cockpit           |
| Signal Tracker  | Coolify ✓     | https://philippe.pamelacoreypc.com/       | LeonidSvb/signal-tracker             |
| Email Verifier  | Coolify ✓     | localhost:8090 (внутри n8n: 172.20.0.1)   | LeonidSvb/email-verifier             |
| Supabase stack  | вне Coolify   | Studio: SSH tunnel :8001                  | /opt/compose/supabase/               |
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

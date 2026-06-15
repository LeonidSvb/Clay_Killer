SERVER ACCESS — netcup-primary
================================
Сервер: v2202604353458453766.hotsrv.de / 152.53.194.162
OS: Debian 13 (trixie), ARM64, 8GB RAM, 256GB NVMe
SSH ключ: %USERPROFILE%\.ssh\id_ed25519_hostinger | sudo пароль: netcup-primary.env → SERVER_ADMIN_PASSWORD


SSH
----
ssh -i ~/.ssh/id_ed25519_hostinger leonid@152.53.194.162


СЕРВИСЫ (основные публичные URL — за Traefik + Cloudflare)
------------------------
n8n:             https://n8n.pamelacoreypc.com/          ← вне Coolify, /opt/compose/n8n/
Cockpit:         https://cockpit.pamelacoreypc.com/      ← Coolify, github: LeonidSvb/outreach-cockpit
Uptime Kuma:     https://uptime.pamelacoreypc.com/       ← вне Coolify, /opt/compose/uptime-kuma/
Coolify:         https://coolify.pamelacoreypc.com/
Signal Tracker:  https://philippe.pamelacoreypc.com/     ← Coolify, github: LeonidSvb/signal-tracker
Supabase API:    https://supabase.pamelacoreypc.com/     ← вне Coolify, /opt/compose/supabase/

Примечание по маршрутизации:
  Traefik (coolify-proxy) слушает порты 80/443
  SSL — Let's Encrypt автоматически при первом запросе на новый домен
  Динамические конфиги: /data/coolify/proxy/dynamic/
  nginx — отключён и disabled (заменён Traefik)

  ВАЖНО — host IP из Docker:
  Traefik в сети coolify (gateway 10.0.2.1)
  Хост-процессы доступны из Traefik как http://10.0.2.1:PORT (не localhost, не 152.53.194.162)
  Docker-контейнеры в coolify-сети — по имени контейнера: http://container-name:PORT

  UFW policy = DROP. Открытые порты: 22, 80, 443, 3001, 8000, 3000, 25, 3333
  Порты только для Docker (10.0.0.0/8): 3099 (signal-tracker), 8001 (supabase)
  Добавить порт для Docker: sudo ufw allow from 10.0.0.0/8 to any port PORT proto tcp


СЕРВИСЫ (только через SSH-туннель)
------------------------------------
Supabase Studio:
  Туннель:  ssh -i ~/.ssh/id_ed25519_hostinger -L 8001:localhost:8001 leonid@152.53.194.162 -N
  Браузер:  http://localhost:8001
  Примечание: порт изменён с 8000 на 8001 (8000 теперь занят Coolify)


СЕРВИСЫ (внутренние, без туннеля)
-----------------------------------
Email Verifier:  http://localhost:8090  (на хосте)
                 http://172.20.0.1:8090  (из n8n контейнера)
  Деплой:        Coolify, github: LeonidSvb/email-verifier
  POST /verify         { "email": "..." }
  POST /verify/batch   { "emails": [...] }
  GET  /health


ПУТИ НА СЕРВЕРЕ
----------------
Compose файлы:   /opt/compose/
  n8n:           /opt/compose/n8n/
  uptime-kuma:   /opt/compose/uptime-kuma/
  supabase:      /opt/compose/supabase/

Coolify:         /data/coolify/source/  (root-owned)
Traefik:
  compose:       /data/coolify/proxy/docker-compose.yml  (root-owned, редактировать base64)
  dynamic:       /data/coolify/proxy/dynamic/  (n8n.yml, cockpit.yml, uptime.yml)
  certs:         /data/coolify/proxy/acme.json

nginx:           ОТКЛЮЧЁН (заменён Traefik)

COOLIFY ПРИЛОЖЕНИЯ (авто-деплой из GitHub при push)
  Cockpit:       uuid=ek9crt7b3m9apigjbfqona76  token: IJXFdkO09V4H2AkgSAf2XK5KDPK2brCl8JlnUOEn
  Email Verif:   uuid=zvktfu62bv2ow0rrtbehyas5  token: NyJrP5NCo4w2K8yCyK2xMtxU0ZDuQhLAg5HbFoJL
  Signal Tracker:uuid=jjqqckwic2ow6nyu3tok8xu8  token: k2ZxCJlBUepjajx2Ug6SFfPO3osbWceVgBx31JTB

  Как добавить GitHub webhook для нового приложения:
  1. Coolify API → получить manual_webhook_secret_github для приложения (это и есть TOKEN)
  2. GitHub: repo → Settings → Webhooks → Add webhook
     Payload URL: https://coolify.pamelacoreypc.com/webhooks/source/github/events/manual?token=TOKEN
     Content type: application/json
     Secret: ТОТ ЖЕ TOKEN (Coolify проверяет HMAC-подпись — без секрета деплой не сработает!)
     Event: Just the push event
  3. Готово — push в main запускает деплой автоматически

  GitHub App (настроен в Coolify):
  Имя: claude-code-coolify-github-app | App ID: 4057976 | Installation ID: 140407354
  Установлен на: все репо аккаунта LeonidSvb
  Назначение: OAuth-интеграция для новых приложений через Coolify UI (не для webhook авто-деплоя)

  GitHub MCP (для Claude):
  Настроен в ~/.claude/settings.json — Claude может управлять репо, вебхуками, файлами через API
  Токен: REDACTED_GITHUB_PAT (repo + admin:repo_hook)

Проекты:         /opt/apps/projects/
  sync-data:     /opt/apps/projects/sync-data/          github: LeonidSvb/sync-data
  PV-sync:       /opt/apps/projects/PV-sync-hack-airtable/  github: LeonidSvb/pv-sync
  Skool:         /opt/apps/projects/skool-scrape-signals/   github: LeonidSvb/skool-scrape-signals
  tg-monitor:    /opt/apps/projects/tg-monitoring/          github: LeonidSvb/tg-monitoring
  fanfic-gen:    /opt/apps/projects/fanfic-gen/             (abandoned)

Бэкапы:         /opt/backups/


POSTGRESQL (хостовый, порт 5432 локально)
------------------------------------------
Существующие базы: icegen, leads, n8n, nocodb, outreach
Подключение через туннель:
  ssh -i ~/.ssh/id_ed25519_hostinger -L 5433:localhost:5432 leonid@152.53.194.162 -N
  затем: psql -h localhost -p 5433 -U postgres

SUPABASE POSTGRESQL (отдельный контейнер)
  порт: 5434 на хосте (127.0.0.1:5434)
  туннель для прямого доступа: ssh -i ~/.ssh/id_ed25519_hostinger -L 5434:localhost:5434 leonid@152.53.194.162 -N
  затем: psql -h 127.0.0.1 -p 5434 -U postgres -d postgres
  password: 4RpLCOvk0B6od6LS6V0FCZhq6dyinGAmTPShxKNGl3M


COOLIFY
--------
URL:        https://coolify.pamelacoreypc.com/
Email:      leo@systemhustle.com
Password:   в netcup-primary.env → COOLIFY_PASSWORD
API Token:  в netcup-primary.env → COOLIFY_API_TOKEN
Server UUID: i31qr902vudauxh8yayi9wsu

API базовые команды:
  BASE="https://coolify.pamelacoreypc.com/api/v1"
  TOKEN=$(grep COOLIFY_API_TOKEN netcup-primary.env | cut -d= -f2)

  # Список сервисов
  curl -s "$BASE/services" -H "Authorization: Bearer $TOKEN" | jq

  # Список приложений
  curl -s "$BASE/applications" -H "Authorization: Bearer $TOKEN" | jq

  # Редеплой приложения
  curl -s "$BASE/deploy?uuid=APP_UUID&force=false" -H "Authorization: Bearer $TOKEN"

  # Добавить env variable
  curl -s -X POST "$BASE/applications/APP_UUID/envs" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"key": "MY_VAR", "value": "my_value", "is_preview": false}'


CLOUDFLARE
-----------
Zone ID:  95b3bb83d3f4c5bd677b016bd8d1c287
Email:    leo@systemhustle.com
API Key:  в netcup-primary.env → CLOUDFLARE_API_KEY

Добавить субдомен:
  curl -s -X POST "https://api.cloudflare.com/client/v4/zones/95b3bb83d3f4c5bd677b016bd8d1c287/dns_records" \
    -H "X-Auth-Email: leo@systemhustle.com" -H "X-Auth-Key: $CLOUDFLARE_API_KEY" \
    -H "Content-Type: application/json" \
    --data '{"type":"A","name":"SUBDOMAIN","content":"152.53.194.162","ttl":1,"proxied":true}'

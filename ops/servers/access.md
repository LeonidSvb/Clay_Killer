SERVER ACCESS
=============
Сервер: v2202604353458453766.hotsrv.de
IP: 152.53.194.162


SSH
----
ssh -i ~/.ssh/id_ed25519_hostinger leonid@152.53.194.162


СЕРВИСЫ (основные публичные URL — за Traefik + Cloudflare)
------------------------
n8n:           https://n8n.pamelacoreypc.com/
Cockpit:       https://cockpit.pamelacoreypc.com/
Uptime Kuma:   https://uptime.pamelacoreypc.com/
Coolify:       https://coolify.pamelacoreypc.com/

Примечание по маршрутизации:
  Traefik (coolify-proxy) слушает порты 80/443
  SSL — Let's Encrypt через Cloudflare DNS Challenge (автообновление)
  Динамические конфиги: /data/coolify/proxy/dynamic/
  nginx — отключён и disabled (заменён Traefik)


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
  Деплой:        /opt/apps/email-verifier/
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

Email Verifier:  /opt/apps/email-verifier/
Outreach Cockpit:/opt/apps/outreach-cockpit/

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

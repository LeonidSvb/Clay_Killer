# Coolify — справочник для деплоя

## Доступ

- URL: https://coolify.pamelacoreypc.com/
- Email: leo@systemhustle.com
- Password: Newbusines2499!
- API Token: `4|372d39f982cce5da69af085522ff5bc5ff83e5fb1f46d901c62bc79c332b6ee1`

## API — базовые команды

```bash
TOKEN="4|372d39f982cce5da69af085522ff5bc5ff83e5fb1f46d901c62bc79c332b6ee1"
BASE="https://coolify.pamelacoreypc.com/api/v1"

# Список серверов
curl -s "$BASE/servers" -H "Authorization: Bearer $TOKEN" | jq

# Список проектов
curl -s "$BASE/projects" -H "Authorization: Bearer $TOKEN" | jq

# Список сервисов
curl -s "$BASE/services" -H "Authorization: Bearer $TOKEN" | jq

# Список приложений
curl -s "$BASE/applications" -H "Authorization: Bearer $TOKEN" | jq
```

## Сервер

- UUID: `i31qr902vudauxh8yayi9wsu`
- Name: localhost
- IP (внутри Docker): host.docker.internal
- is_reachable: true, is_usable: true

## Как деплоить новый сервис (через API)

### 1. Создать проект
```bash
curl -s -X POST "$BASE/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-project", "description": "..."}'
# Вернёт project UUID
```

### 2. Задеплоить публичный GitHub репозиторий
```bash
curl -s -X POST "$BASE/applications/public" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project_uuid": "PROJECT_UUID",
    "server_uuid": "i31qr902vudauxh8yayi9wsu",
    "environment_name": "production",
    "git_repository": "https://github.com/LeonidSvb/repo-name",
    "git_branch": "main",
    "build_pack": "dockerfile",
    "name": "service-name",
    "domains": "https://subdomain.pamelacoreypc.com",
    "ports_exposes": "3000"
  }'
```

### 3. Задеплоить Docker Compose
```bash
curl -s -X POST "$BASE/services" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project_uuid": "PROJECT_UUID",
    "server_uuid": "i31qr902vudauxh8yayi9wsu",
    "environment_name": "production",
    "name": "service-name",
    "docker_compose_raw": "version: '\''3'\''\\nservices:\\n  app:\\n    image: myimage:latest"
  }'
```

### 4. Редеплой существующего приложения
```bash
curl -s -X GET "$BASE/deploy?uuid=APP_UUID&force=false" \
  -H "Authorization: Bearer $TOKEN"
```

### 5. Добавить env variable
```bash
curl -s -X POST "$BASE/applications/APP_UUID/envs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"key": "MY_VAR", "value": "my_value", "is_preview": false}'
```

## Домены

Все домены на `pamelacoreypc.com`. Cloudflare Zone ID: `95b3bb83d3f4c5bd677b016bd8d1c287`

Добавить новый субдомен через Cloudflare API:
```bash
curl -s -X POST "https://api.cloudflare.com/client/v4/zones/95b3bb83d3f4c5bd677b016bd8d1c287/dns_records" \
  -H "X-Auth-Email: leo@systemhustle.com" \
  -H "X-Auth-Key: REDACTED_CF_API_KEY" \
  -H "Content-Type: application/json" \
  --data '{"type":"A","name":"SUBDOMAIN","content":"152.53.194.162","ttl":1,"proxied":true}'
```

Существующие субдомены:
- n8n.pamelacoreypc.com → n8n-app:5678
- cockpit.pamelacoreypc.com → outreach-cockpit:3002
- uptime.pamelacoreypc.com → uptime-kuma:3001
- coolify.pamelacoreypc.com → coolify:8080

## Traefik — добавить новый домен вручную

Если сервис вне Coolify (запущен через docker-compose вручную):
```bash
# 1. Создать /data/coolify/proxy/dynamic/SERVICENAME.yml (через base64+sudo)
# 2. Подключить Traefik к сети сервиса:
docker network connect NETWORK_NAME coolify-proxy
```

Динамические конфиги: `/data/coolify/proxy/dynamic/`
Файлы: n8n.yml, cockpit.yml, uptime.yml, coolify.yml

## Существующие сервисы (вне Coolify, управляются вручную)

| Сервис | Compose | Сеть |
|---|---|---|
| n8n | /opt/compose/n8n/ | n8n_default |
| Supabase | /opt/compose/supabase/ | supabase_default |
| Uptime Kuma | /opt/compose/uptime-kuma/ | uptime-kuma_default |
| outreach-cockpit | /opt/apps/outreach-cockpit/ | outreach-cockpit_cockpit-net |
| email-verifier | /opt/apps/email-verifier/ | (bridge) |
| shared-postgres | docker run напрямую | (bridge) |

Эти сервисы НЕ видны в Coolify UI — управляются через SSH.

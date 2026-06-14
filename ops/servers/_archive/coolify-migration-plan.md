# Coolify — план миграции v2
Дата обновления: 2026-06-08
Сервер: 152.53.194.162 (netcup VPS, 8 GB RAM, 256 GB NVMe, Debian 13)

---

## Что нашли на сервере (ресёрч)

### Реальное состояние контейнеров
| Сервис | Статус | RAM | Примечание |
|---|---|---|---|
| metabase | Up 5 weeks | **983 MB** | Не нужен — убиваем первым |
| supabase-db | Up 5 weeks | — | bind-mount: /opt/compose/supabase/volumes/db/data |
| supabase-kong | Up 5 weeks | — | 8000 порт на хосте |
| supabase-studio | Up 5 weeks | — | |
| supabase-rest | Up 5 weeks | — | |
| supabase-auth | Up 5 weeks | — | |
| supabase-meta | Up 5 weeks | — | |
| n8n-app | Up 5 weeks | — | volume: n8n_n8n_data |
| n8n-postgres | Up 6 weeks | — | volume: n8n_postgres_data |
| outreach-cockpit | Up 14 hours | — | network_mode: host, порт 3002 |
| outreach-cockpit-api | Up 14 hours | — | network_mode: host, порт 3003 |
| email-verifier | Up 9 days | — | порт 8090, подключён к n8n_default сети |
| uptime-kuma | Up 5 weeks | — | volume: uptime-kuma_uptime-kuma-data |
| shared-postgres | Up 6 weeks | — | хостовый PG, 127.0.0.1:5432 |

### Git-статус проектов
| Проект | Git | GitHub remote |
|---|---|---|
| sync-data | НЕТ | НЕТ |
| skool-scrape-signals | НЕТ | НЕТ |
| email-verifier | НЕТ | НЕТ |
| tg-monitoring | есть | НЕТ |
| fanfic-gen | есть | НЕТ |
| PV-sync-hack-airtable | есть | github.com/LeonidSvb/pv-sync.git |

### Прочие находки
- **swap = 0** — нет swap вообще. Риск OOM при миграции. Добавляем 4 GB в Phase 0.
- **outreach-sync** — `/opt/apps/projects/outreach-sync/` запускался один раз вручную 7 июня (при миграции), в cron нет. `/opt/apps/outreach-sync/` — пустая папка. Оба — мёртвый легаси. Не мигрируем, не трогаем.
- **apps.conf.new** — nginx-конфиг для cockpit уже написан, но файл с суффиксом `.new`. Нужно активировать.
- **sync-data** содержит `google-service-account.json` — в GitHub пойдёт с `.gitignore` на этот файл.
- **email-verifier** — уже в Docker (собирается из `./app`), просто нет git-репо.

---

## Решения по всем вопросам

**Email Verifier**: создаём GitHub репо, пушим с сервера → управляем через Coolify. Сборка из Dockerfile.
Сетевая зависимость от `n8n_default` убирается: n8n будет обращаться к verifier через `http://172.17.0.1:8090` (мост к хосту), как сейчас и делает.

**Uptime Kuma**: копируем volume в бэкап → в новом Coolify-инстансе восстанавливаем через `docker cp`. Мониторы не пересоздаём вручную.

**Cron-скрипты** (sync-data, skool-scrape-signals, tg-monitoring): **остаются на системном cron**. Coolify не нужен для cron-задач — это усложнение без пользы. Только пушим в GitHub для безопасности.

**Supabase PostgreSQL**: данные хранятся как bind-mount → `/opt/compose/supabase/volumes/db/data`. При импорте docker-compose.yml в Coolify путь сохраняется, данные никуда не переезжают.

**kong.yml**: остаётся на filesystem сервера как bind-mount. В GitHub не нужен.

**outreach-cockpit network_mode: host**: **БЛОКЕР для Coolify**. Traefik не может маршрутизировать трафик к контейнерам с host-сетью. Нужно переделать на bridge перед миграцией (Phase 0.4).

**n8n данные**: экспортируем все workflows + credentials через n8n UI → импортируем в новый инстанс с тем же `N8N_ENCRYPTION_KEY`. Чище и надёжнее чем volume-миграция.

**Rollback**: каждая фаза — старый контейнер **останавливается, но не удаляется**. Если что-то сломалось — `docker compose up -d` в старом compose-директории, всё поднимется обратно.

---

## Phase 0 — Подготовка (выполнить полностью до Coolify)

### 0.0 Убить Metabase (освободит ~1 GB RAM)
```bash
cd /opt/compose/metabase && docker compose down
```

### 0.1 Добавить swap (защита от OOM при миграции)
```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 0.2 Бэкап всего
```bash
# PostgreSQL хостовый
pg_dumpall -U postgres > /opt/backups/pre-coolify-$(date +%Y%m%d).sql

# Все compose-директории
tar -czf /opt/backups/compose-$(date +%Y%m%d).tar.gz /opt/compose/

# n8n volumes (named volumes → tar)
docker run --rm \
  -v n8n_n8n_data:/n8n \
  -v n8n_postgres_data:/pg \
  -v /opt/backups:/backup \
  alpine tar czf /backup/n8n-volumes-$(date +%Y%m%d).tar.gz /n8n /pg

# Uptime Kuma
docker cp uptime-kuma:/app/data /opt/backups/uptime-kuma-data

# Скачать всё локально через scp
```

### 0.3 Экспорт n8n (через UI, пока работает)
- n8n → Settings → Export → Export All Workflows (JSON)
- n8n → Credentials → экспортировать каждый (или через API)
- Сохранить `N8N_ENCRYPTION_KEY` из `/opt/compose/n8n/.env`

### 0.4 Пушить проекты в GitHub

**sync-data** — git уже есть ЛОКАЛЬНО на `C:\Users\79818\Desktop\sync-data`. Пушим оттуда:
```powershell
cd C:\Users\79818\Desktop\sync-data
# создать репо на GitHub (github.com/new), потом:
git remote add origin https://github.com/LeonidSvb/sync-data.git
git push -u origin master
```
Затем на сервере синхронизировать:
```bash
cd /opt/apps/projects/sync-data
echo "google-service-account.json" > .gitignore
echo ".env" >> .gitignore
echo "sync.log" >> .gitignore
echo "node_modules/" >> .gitignore
git init && git remote add origin https://github.com/LeonidSvb/sync-data.git
git fetch origin && git reset --hard origin/master
```

**email-verifier** (нет git):
```bash
cd /opt/apps/email-verifier
echo ".env" > .gitignore
git init && git add . && git commit -m "init"
git remote add origin https://github.com/LeonidSvb/email-verifier.git
git push -u origin master
```

**skool-scrape-signals** (нет git):
```bash
cd /opt/apps/projects/skool-scrape-signals
echo ".env\nvenv/\n*.log\ndb/*.db" > .gitignore
git init && git add . && git commit -m "init"
git remote add origin https://github.com/LeonidSvb/skool-scrape-signals.git
git push -u origin master
```

**tg-monitoring и fanfic-gen** (есть git, нет remote):
```bash
# создать репо на GitHub, потом на сервере:
git -C /opt/apps/projects/tg-monitoring remote add origin https://github.com/LeonidSvb/tg-monitoring.git
git -C /opt/apps/projects/tg-monitoring push -u origin master

git -C /opt/apps/projects/fanfic-gen remote add origin https://github.com/LeonidSvb/fanfic-gen.git
git -C /opt/apps/projects/fanfic-gen push -u origin master
```

### 0.5 Рефакторинг outreach-cockpit (убрать network_mode: host)

Текущая проблема: оба контейнера на host-сети → Traefik не может их достучаться.

Нужно изменить в `/opt/apps/outreach-cockpit/`:

**docker-compose.yml** — убрать `network_mode: host`, добавить нормальные порты и сеть:
```yaml
services:
  cockpit:
    image: nginx:alpine
    container_name: outreach-cockpit
    restart: unless-stopped
    ports:
      - "3002:3002"
    volumes:
      - /opt/apps/outreach-cockpit:/usr/share/nginx/html:ro
      - /opt/apps/outreach-cockpit/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    networks:
      - cockpit-net

  api:
    build:
      context: /opt/apps/outreach-cockpit
      dockerfile: Dockerfile.server
    container_name: outreach-cockpit-api
    restart: unless-stopped
    environment:
      PORT: "3003"
      PG_HOST: "172.17.0.1"   # Docker bridge gateway к хосту
      PG_PORT: "5434"
      PG_DB: postgres
      PG_USER: postgres
      PG_PASS: "4RpLCOvk0B6od6LS6V0FCZhq6dyinGAmTPShxKNGl3M"
    networks:
      - cockpit-net

networks:
  cockpit-net:
    driver: bridge
```

**nginx.conf** — изменить proxy_pass с localhost на имя сервиса:
```nginx
location /api/ {
    proxy_pass http://outreach-cockpit-api:3003;
    ...
}
```

После изменений — пересобрать и проверить:
```bash
cd /opt/apps/outreach-cockpit
docker compose down && docker compose up -d --build
# проверить что cockpit.pamelacoreypc.com открывается и данные грузятся
```

### 0.6 Открыть порт 3333 для Coolify UI
```bash
sudo ufw allow 3333/tcp
sudo ufw allow 8000/tcp  # если закрыт — нужен для Supabase пока
```

---

## Phase 1 — Установка Coolify

```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
```

Coolify поднимется на порту 8000. Supabase тоже на 8000 → конфликт.
**Порядок**: остановить Supabase ДО запуска инсталлятора:
```bash
cd /opt/compose/supabase && docker compose down   # данные в /volumes/db/data — не удаляются
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
```

После установки — сменить порт Coolify:
```bash
# в /data/coolify/.env
APP_PORT=3333
# перезапустить
cd /data/coolify && docker compose restart
```

Открыть `http://152.53.194.162:3333` → создать аккаунт.

---

## Phase 2 — Настройка Traefik + Cloudflare SSL

Traefik заменяет nginx. SSL через Let's Encrypt с DNS-challenge (Cloudflare).

**Получить Cloudflare API Token:**
Cloudflare Dashboard → My Profile → API Tokens → Create Token → шаблон "Edit zone DNS" → зона pamelacoreypc.com → создать.

**В Coolify UI:**
1. Settings → Proxy → Traefik (выбрать)
2. Wildcard SSL → DNS challenge → Cloudflare → ввести API Token

**Остановить nginx после настройки Traefik:**
```bash
systemctl stop nginx && systemctl disable nginx
```

---

## Phase 3 — Uptime Kuma

1. Coolify UI → New Service → Uptime Kuma (one-click)
2. После запуска нового контейнера — перенести данные:
```bash
# найти имя нового контейнера
docker ps | grep kuma

# скопировать данные из бэкапа
docker cp /opt/backups/uptime-kuma-data NEW_CONTAINER_NAME:/app/data
docker restart NEW_CONTAINER_NAME
```
3. Проверить что мониторы появились → остановить старый:
```bash
cd /opt/compose/uptime-kuma && docker compose down
```

---

## Phase 4 — Email Verifier

1. Coolify UI → New Resource → Application → GitHub → выбрать репо email-verifier
2. Build: Dockerfile в `./app/`
3. Port: 3000 (внутренний), expose как 8090 на хосте
4. ENV: `NODE_ENV=production`, `BATCH_CONCURRENCY=20`
5. Добавить в ту же Coolify-сеть что и n8n (или оставить на порту хоста)
6. Проверить: `curl http://localhost:8090/health`
7. Остановить старый: `cd /opt/apps/email-verifier && docker compose down`

---

## Phase 5 — outreach-cockpit

К этому моменту уже сделан рефакторинг на bridge-сеть (Phase 0.5) и он работает.

1. Coolify UI → New Resource → Docker Compose → вставить обновлённый docker-compose.yml
2. Добавить домен `cockpit.pamelacoreypc.com` → Traefik выдаст сертификат
3. Убрать порт `3002` из ports (Traefik сам маршрутизирует через сеть)
4. Проверить что данные грузятся, API работает
5. Остановить старый: `cd /opt/apps/outreach-cockpit && docker compose down`

---

## Phase 6 — n8n

### Перед миграцией
Убедиться что экспорт из Phase 0.3 сделан.

### В Coolify
1. New Service → n8n
2. Env vars — скопировать из `/opt/compose/n8n/.env`:
   - `N8N_ENCRYPTION_KEY` — **критично, должен совпадать**
   - `N8N_HOST=n8n.pamelacoreypc.com`
   - `N8N_PROTOCOL=https`
   - `WEBHOOK_URL=https://n8n.pamelacoreypc.com/`
   - `N8N_EDITOR_BASE_URL=https://n8n.pamelacoreypc.com/`
   - `N8N_SECURE_COOKIE=true`
   - все остальные из .env
3. Домен: `n8n.pamelacoreypc.com` → Traefik выдаст сертификат (заменит self-signed)
4. Запустить → войти → импортировать workflows и credentials из бэкапа
5. Проверить что webhooks работают через публичный URL
6. Остановить старый:
```bash
cd /opt/compose/n8n && docker compose down
```

---

## Phase 7 — Supabase minimal

Данные уже на диске в `/opt/compose/supabase/volumes/db/data`.

1. Coolify UI → New Resource → Docker Compose
2. Вставить содержимое `/opt/compose/supabase/docker-compose.yml`
3. Env vars: перенести из `/opt/compose/supabase/.env`
4. Bind mounts для volumes должны ссылаться на те же пути (`/opt/compose/supabase/volumes/...`)
   — данные никуда не переезжают, они уже на диске
5. Если Coolify переписывает пути — вручную отредактировать compose в UI
6. Запустить → Studio должен открыться через Traefik
7. Проверить данные: outreach схема, 27922 лидов
8. Проверить что sync-data и PV-sync подключаются

**Примечание по kong.yml**: остаётся как bind-mount из `/opt/compose/supabase/volumes/api/kong.yml`.

---

## Phase 8 — Host PostgreSQL → Supabase (не срочно)

Делать через 2-3 недели после того как Coolify стабильно работает.
Базы: icegen, leads, outreach — перенести pg_dump → restore в Supabase PostgreSQL.
Базы n8n, nocodb — не нужны (n8n использует свой контейнер, nocodb не запущен).

---

## Чеклист перед стартом

- [ ] Cloudflare API Token получен (Zone:DNS:Edit для pamelacoreypc.com)
- [ ] Бэкапы сделаны и скачаны локально (Phase 0.2)
- [ ] n8n workflows + credentials экспортированы (Phase 0.3)
- [ ] Все проекты в GitHub (Phase 0.4)
- [ ] outreach-cockpit переделан на bridge и протестирован (Phase 0.5)
- [ ] Metabase убит (Phase 0.0)
- [ ] Swap добавлен (Phase 0.1)
- [ ] Есть 3-4 часа свободного времени

---

## Rollback — как вернуться если что-то сломалось

**Для любого сервиса**: старый compose-директорий не удалён → просто поднять обратно:
```bash
cd /opt/compose/n8n && docker compose up -d
cd /opt/compose/supabase && docker compose up -d
cd /opt/apps/outreach-cockpit && docker compose up -d
```

nginx конфиг сохранён → включить обратно:
```bash
systemctl enable nginx && systemctl start nginx
```

---

## RAM после полной миграции

| | Было | Станет |
|---|---|---|
| Metabase | 983 MB | 0 (убран) |
| nginx | 50 MB | 0 (убран) |
| Coolify + Traefik + Redis | 0 | +500 MB |
| Все сервисы | ~4.4 GB | ~3.9 GB |
| Swap | 0 | 4 GB (резерв) |
| **Свободно** | **~3.3 GB** | **~3.8 GB** |

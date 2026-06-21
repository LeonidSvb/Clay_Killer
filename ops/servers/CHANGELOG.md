# CHANGELOG — netcup-primary server ops

## [2026-06-21]

### Claude Code на сервере
- Установлен Claude Code v2.1.185 (Node.js v20 уже был)
- OAuth логин через Pro подписку (claude.ai), без API ключа
- Развёрнут ttyd веб-терминал — `https://term.pamelacoreypc.com`
- Basic auth: логин `leonid`, пароль из netcup-primary.env
- tmux сессия `claude` — переподключение при обновлении страницы
- systemd сервис `ttyd` — автозапуск при перезагрузке сервера
- UFW: открыт порт 7681 для Docker-сети (10.0.0.0/8)
- Cloudflare DNS A-запись `term` → 152.53.194.162
- Traefik dynamic config: `/data/coolify/proxy/dynamic/term.yml`

---

## [2026-06-15]

### GitHub интеграция
- Задокументированы webhook secrets, GitHub App, MCP настройки для Coolify

---

## [2026-06-14]

### Реструктуризация ops/servers
- Приведены к единому стандарту: access.md, CLAUDE.md, netcup-primary.env

---

## [2026-06-08]

### Coolify / Traefik миграция завершена
- Coolify поднят на порту 8000, добавлен coolify-reference.md
- Traefik заменил nginx — обрабатывает 80/443, SSL через Cloudflare DNS Challenge
- Динамические конфиги в `/data/coolify/proxy/dynamic/`

---

## [2026-06-07]

### sync-data
- CLAUDE.md обновлён: sync pipeline переведён на проект sync-data

---

## [2026-04-26]

### Первоначальная документация сервера
- Добавлены shared reference файлы сервера
- Задокументирован стек: n8n, Supabase, shared-postgres, Uptime Kuma
- Зафиксировано состояние миграции с Hostinger на Netcup
- Записаны задеплоенные директории приложений

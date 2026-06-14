BACKLOG — netcup-primary
========================
Только открытые задачи. Выполненные — в _archive/TODO.txt


UPTIME KUMA (сделать вручную через UI на https://uptime.pamelacoreypc.com/)
------------------------------------------------------------------------------
[ ] Добавить мониторы:
    - n8n:        https://n8n.pamelacoreypc.com/ (HTTP keyword)
    - cockpit:    https://cockpit.pamelacoreypc.com/ (HTTP)
    - uptime:     https://uptime.pamelacoreypc.com/ (HTTP self)
    - sync-data:  Heartbeat (скрипт должен пинговать после каждого запуска)
    - tg-monitor: Heartbeat
    - skool:      Heartbeat
[ ] Telegram нотификации


БАЗЫ ДАННЫХ
------------
[ ] Перенести icegen из shared-postgres в Supabase (опционально, не срочно)


METABASE
---------
[ ] Поднять когда нужны дашборды
    Туннель: ssh -i ~/.ssh/id_ed25519_hostinger -L 3000:localhost:3000 leonid@152.53.194.162 -N
    Данные: Supabase DB metabase schema, compose: /opt/compose/metabase/


EMAIL VERIFIER (/opt/apps/email-verifier/)
-------------------------------------------
[ ] Rate limiter по MX провайдеру (защита IP при 20k+/день)
[ ] Bounce feedback loop — POST /bounce + SQLite кэш плохих доменов
[ ] Persistent DNS cache (сейчас сбрасывается при рестарте контейнера)
[ ] Google Workspace API verification (OAuth) — решит bucket unknown/no_connect

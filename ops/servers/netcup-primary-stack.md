# netcup-primary stack

Host:
- Provider: netcup
- Hostname: `v2202604353458453766.hotsrv.de`
- IPv4: `152.53.194.162`
- OS: `Debian 13 (trixie)`

Access:
- SSH user: `leonid`
- Root SSH login: disabled
- Password SSH login: disabled
- Local SSH key: `%USERPROFILE%\\.ssh\\id_ed25519_hostinger`

Installed base stack:
- `ufw`
- `fail2ban`
- `unattended-upgrades`
- `docker`
- `docker compose`
- `nginx`
- `nodejs`
- `npm`
- `python3`
- `pip3`
- `postgresql`

Open ports:
- `22/tcp` for SSH
- `80/tcp` for HTTP
- `443/tcp` reserved for future HTTPS

Deploy paths:
- `/opt/apps`
- `/opt/apps/_inventory`
- `/opt/apps/projects`
- `/opt/compose`
- `/opt/compose/n8n`

Active app stack:
- `n8n` in Docker Compose
- `postgres:17-alpine` container for n8n
- n8n bind: `127.0.0.1:5678`
- n8n external hostname: `n8n.pamelacoreypc.com`
- nginx reverse proxy path: `/`
- nginx upstream rule: `proxy_pass http://127.0.0.1:5678;`
- nginx serves `80` and `443` for `n8n.pamelacoreypc.com`
- origin TLS cert path: `/etc/nginx/ssl/n8n.pamelacoreypc.com.crt`
- n8n cookie mode: `N8N_SECURE_COOKIE=true`
- n8n public URL: `https://n8n.pamelacoreypc.com/`
- verified after fix:
  - public Cloudflare URL returns `200`
  - origin HTTPS on `443` returns HTML
  - Cloudflare `521` cleared

Hostinger migration status:
- backup source: `C:\Users\79818\Desktop\hostinger-backup-2026-04-19.tar.gz`
- migration files on server: `/opt/migration/hostinger-2026-04-19`
- restored host PostgreSQL databases: `icegen`, `leads`, `metabase`, `n8n`, `nocodb`, `outreach`
- imported into n8n: `26` credentials
- imported into n8n: `36` workflows

Migrated local projects:
- `/opt/apps/projects/PV-sync-hack-airtable` - git history preserved, head `f2f47d0`
- `/opt/apps/projects/fanfic-gen` - git history preserved, head `223c693`
- `/opt/apps/projects/tg-monitoring` - git history preserved, head `5472b9f`
- `/opt/apps/projects/skool-scrape-signals` - files only, no local `.git` existed

Notes:
- SMTP intentionally left unused
- Reconnect SSH after group changes to use Docker without sudo
- Domain/HTTPS deferred by decision; current access works by IP
- Update: n8n now uses a dedicated Cloudflare-backed hostname; remaining improvement is replacing the self-signed origin cert with a trusted cert or Cloudflare Origin CA

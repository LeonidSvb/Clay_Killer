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
- `/opt/compose`
- `/opt/compose/n8n`

Active app stack:
- `n8n` in Docker Compose
- `postgres:17-alpine` container for n8n
- n8n bind: `127.0.0.1:5678`
- nginx reverse proxy path: `/n8n/`
- n8n public URL: `http://152.53.194.162/n8n/`

Notes:
- SMTP intentionally left unused
- Reconnect SSH after group changes to use Docker without sudo
- Next step: attach a domain and enable HTTPS

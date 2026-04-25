# Server References

Use the local env files in this folder for shared infrastructure references across projects.

Files:
- `ops/servers/netcup-primary.env` - live local server data and credentials, ignored by git
- `ops/servers/netcup-primary.env.example` - committed non-secret template
- `ops/servers/netcup-primary-stack.md` - committed inventory of the installed server stack

Current server:
- Provider: netcup
- Label: `netcup-primary`
- Hostname: `v2202604353458453766.hotsrv.de`
- IPv4: `152.53.194.162`
- Admin user: `leonid`
- SSH key: `%USERPROFILE%\\.ssh\\id_ed25519_hostinger`
- n8n URL: `http://152.53.194.162/n8n/`
- Remote inventory: `/opt/apps/_inventory/SERVER_STACK.md`

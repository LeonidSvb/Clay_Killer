ICEGEN EXPORT MANIFEST
======================
Дата: 2026-04-29

ПАПКА
-----
`lead_exports/icegen/`

ЧТО ПРОВЕРЕНО
-------------
1. Хостовый PostgreSQL container: `shared-postgres`
   - databases:
     - `platform`
     - `outreach_sync`
     - `tg_monitoring`
   - в live-базах `platform` и `outreach_sync` relations для `icegen` изначально не было
   - затем из `/opt/migration/hostinger-2026-04-19/postgres-all-databases.sql`
     был отдельно восстановлен дамп базы `icegen`

2. Supabase PostgreSQL container: `supabase-db`
   - databases:
     - `_supabase`
     - `postgres`
   - в `postgres`: только системные Supabase relations (`auth`, и т.д.)
   - пользовательских схем/таблиц `icegen` не найдено

ЧТО ВЫГРУЖЕНО
-------------
Источник: восстановленный `icegen` из host migration dump

- `configs.csv`             — 1 row
- `extractions.csv`         — 76 rows
- `generations.csv`         — 185 rows
- `inputs.csv`              — 101 rows
- `prompts.csv`             — 8 rows
- `runs.csv`                — 15 rows
- `schema_migrations.csv`   — 7 rows
- `source_files.csv`        — 2 rows

ВЫВОД
-----
- В живом `Supabase` данных `icegen` не было.
- В живом host `shared-postgres` база `icegen` тоже не была восстановлена.
- Реальный источник данных оказался в migration dump:
  `/opt/migration/hostinger-2026-04-19/postgres-all-databases.sql`
- CSV-экспорт `icegen` собран локально в эту папку.

# WebScraping_Exa — Project Context for Claude

## Database Schema

PostgreSQL schema (outreach DB on Hostinger VPS):
`C:\Users\79818\Desktop\Outreach_XX\db\schema.sql`

ALWAYS read this file before writing any SQL or DB queries.
Migrations run ONLY from Outreach_XX — this project does NOT modify the schema.

Database connection details are in `.env` (DATABASE_URL or individual POSTGRES_* vars).

## Ground Rules

- Do not create migration files here — all schema changes go in Outreach_XX
- Check schema.sql before assuming column names, types, or table structure

# Project Context — Leo / System Hustle

## Role
Leo is a BD connector. He does not sell a product — he connects companies with their ICP.

## The Model
- Outreach angle: "I work with companies in your space looking for [their ICP]"
- No Rolodex ready right now — the value is the system: monitoring market signals to find the right moment
- Not bait and switch — honest framing: "I build the system for you, I don't sell a list"

## Language Rules
- Объяснения, инсайты, "почему это важно", "как использовать" — всегда на русском
- Фразы и цитаты которые Leo будет говорить вслух — всегда на простом английском, без усложнений. Все звонки на английском, независимо от языка переписки/прospectа — не уточнять, не обсуждается.
- Простой английский = короткие предложения, разговорный стиль, без корпоративщины

## Prospect Brief Format
brief.md — сквозной рассказ (см. templates/prospect-research-template.md): 1. Кто он → 2. Бизнес → 3. TAM (страны, кол-во компаний по критериям, % достижимо email, % активно нуждаются сейчас, сигналы ниши + объём/мес) → 4. Экономика ниши (если нетривиальная) → 5. ICP и сигналы → 6. Ретейнер — потянет ли → 7. Red flags и тон.
Вопросы/питч/возражения/цена — только в call-script.md, не дублировать в brief.md.

## Script Rules
- Always mark pauses explicitly: [PAUSE]
- Always offer two specific time options, never open-ended "when works for you"
- Always double-check prospect's name manually before sending — never trust autofill

## Niches
- Old-school B2B: logistics, trucking, packaging, distribution, manufacturing
- Recruiting agencies (separate framework)

## Folder Structure
- templates/ — reusable scripts and frameworks (proposals/, kickoff/, case-studies/, _reference/ = archived source material, not active)
- prospects/[name]/ — one folder per prospect, brief.md inside. Новые папки с 2026-07-04: `YYYY-MM-DD-name` (дата первого звонка) для хронологической сортировки. Старые не переименованы.
- scripts/utils/exa-search.sh "query" [numResults] [maxChars] — ресёрч через Exa (глубже чем WebSearch), ключ в .env
- CHANGELOG.md — только структурные изменения системы, не рутинная работа по прospectам

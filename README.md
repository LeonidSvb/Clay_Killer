# System Hustle — Sales Toolkit

Signal-based BD tools for recruiting agencies. Hosted at systemhustle.com.

---

## Pages

### Public

| Page | URL | Description |
|---|---|---|
| Pre-call VSL | `/signal-intro.html` | 6-slide deck sent before the sales call. Record with Loom. |
| Order form | `/order-form.html` | Post-call closing page. Personalized via URL params. |

### Internal (password protected)

| Page | URL | Description |
|---|---|---|
| Sales pitch deck | `/signal-deck.html` | 7-slide deck for the sales call. Use with screen share. |
| Link generator | `/link-generator.html` | Generates order form URL + email draft after each call. |

---

## Order form URL params

```
/order-form.html?name=Rob&tier=pilot&intros=2-3
```

| Param | Values | Description |
|---|---|---|
| `name` | any | Client first name |
| `tier` | `pilot` / `full` | Starter Pilot ($800) or Full Package ($3,000/mo) |
| `intros` | e.g. `2-3` | Override guaranteed intro count (optional) |

---

## Sales flow

```
1. Record Loom using signal-intro.html → send before call
2. Run call using signal-deck.html
3. They say yes → open link-generator.html → copy link + email
4. Send email with PayPal link + order form URL
5. They pay → kickoff call within 48h
```

---

## Local files (not deployed)

| File | Description |
|---|---|
| `call_prep_rob.md` | Call prep — Rob Berton / Locum Tenens USA |
| `call_prep_vincent.md` | Call prep — Vincent Burger / NorTek Medical |
| `research_prompt.txt` | Exa AI research prompt for new prospects |
| `loom-script.md` | Script for the Loom VSL recording |
| `email-templates.md` | Post-call email templates (pilot + full) |
| `.env` | `EXA_API_KEY` — not committed |

---

leo@systemhustle.com

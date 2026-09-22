# RicozChange

AI-native IT change management — MVP. FastAPI + SQLite backend, React + Vite frontend.

## What makes it different

| Feature | Where |
|---|---|
| **Explainable risk score** — every point has a line item ("+15: Payments DB is business-critical") | Change detail → "Why this score"; also inside Slack messages |
| **Collision detector** — warns when changes overlap on shared systems | Automatic on the detail page + live in the Simulator |
| **Change Simulator** — drag sliders, watch score/collisions/blast radius react | `/simulator` |
| **Blast-radius map** — dependency graph; a change lights up everything it touches | `/graph` and every detail page |
| **Auto fast-track** — standard templates under score 25 approve in one click | Submit any standard change |
| **AI-drafted rollback / test / comms plans** — human-approved, never auto-applied | Detail page → "AI drafting" |
| **Slack-style approvals** — approve with the "why" inline | `/slack` demo outbox |
| **Post-change check + CFR dashboard** — "did it work?" feeds the failure rate | Dashboard KPI |

## Quickstart (no API keys needed)

```bash
# 1. Backend (Python 3.11+)
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Windows
# .venv/bin/pip install -r requirements.txt        # macOS/Linux
.venv/Scripts/python -m uvicorn ricozchange.main:app --port 8000

# 2. Frontend (Node 18+)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The database seeds itself on first boot with systems,
dependency edges, a freeze window, CAB meeting, history and one risky pending change
(#7 — approve it from the Slack demo page).

## Deploy to Render (free, one URL for your manager)

The repo ships a Render Blueprint: one free web service (FastAPI serving the built SPA — no CORS setup, single URL) plus a free managed Postgres, linked automatically.

**1. Push the deploy files** (if not already pushed):

```bash
git add -A
git commit -m "deploy: Render blueprint (single service + free Postgres)"
git push
```

**2. Two clicks on Render:**

1. Sign in at [dashboard.render.com](https://dashboard.render.com) with GitHub (free account).
2. **New → Blueprint** → pick the `RicozChange` repo (grant access if prompted) → **Apply**.
3. Wait ~5 minutes for the first build. Your URL appears at the top: `https://ricozchange-xxxx.onrender.com`.

Good to know:

- First load after inactivity takes up to ~60 s (free tier spins down); the app shows a "Waking up…" screen and retries automatically.
- Data lives in the free Postgres (1 GB, expires after 30 days — recreate the database or upgrade to keep it). Seeding runs automatically whenever the database is empty.
- Enable Claude drafting any time: service → **Environment** → add `ANTHROPIC_API_KEY`.
- Every push to `main` auto-deploys.
- `ANTHROPIC_API_KEY`, `GATE_BY_DEMO_USER`, Clerk vars: same names as local config (see `backend/.env.example`); none are required.

## 3-minute demo script

1. **Dashboard** — CFR KPI and top open risk.
2. Open change **#7** — walk the "Why this score" panel (major base + tier-0 systems + past failure on payments-db − overnight mitigation).
3. **Slack demo** — hit ✅ Approve; the change flips to approved (any-of policy).
4. **Simulator** — drag the window slider; show score, collisions and blast radius moving live.
5. Back on the change: **Start implementing → Mark completed → post-change check** → dashboard CFR updates.

## Configuration (all optional)

Copy `backend/.env.example` → `.env`. Highlights:

- `ANTHROPIC_API_KEY` — enables Claude-drafted plans; without it, deterministic template drafts are used.
- `DATABASE_URL` — defaults to SQLite at `data/Ricozchange.db`; use Postgres in production.
- `GATE_BY_DEMO_USER=true` + Clerk vars — real auth via Clerk JWKS; demo mode is single-user.

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest tests/ -q
```

## Layout

```
backend/
  ricozchange/
    main.py          FastAPI routes
    models.py        SQLAlchemy domain (Change, System, Approval, CAB, Freeze, Audit…)
    risk_engine.py   explainable scoring, collisions, freezes, safe windows
    ai_drafting.py   Claude drafting + template fallback
    services.py      workflow state machine, seeding, CSV import
    auth.py          demo/Clerk identity
  tests/             end-to-end API tests
frontend/
  src/pages/         Dashboard, Changes, ChangeForm, ChangeDetail, Simulator,
                     GraphPage, CABPage, SlackDemo, Freezes
  src/components/    RiskWhy panel, BlastRadiusGraph (React Flow)
docker-compose.yml   api + web (nginx serving the built SPA)
Dockerfile.render    single-service image (SPA baked into the API) for Render
render.yaml          Render Blueprint: web service + free managed Postgres
```

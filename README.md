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
| **Real Slack integration** (phase 2) — OAuth install, DMs with the "why", approve/reject buttons in Slack, signed callbacks | Slack setup below |
| **Email-to-change** (phase 2) — file a change by emailing the mailbox; parsed, scored, filed as a draft, auto-reply with the score + "why" | Email setup below · Integrations page simulator |
| **Email sweeps** — post-change "did it work?" prompts, daily pending-approval digests, fallbacks when Slack delivery fails | `POST /api/integrations/email/sweep` · Integrations page |
| **Deploy-as-change** (v0.3) — a production deploy on a connected repo becomes a scored, collision-checked change; deploy status records the outcome | GitHub setup below · Integrations page |
| **Calendar feed** (v0.3) — subscribe to change windows and freezes from Google Calendar / Outlook (read-only .ics) | Integrations page → Calendar feed |
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

1. **Dashboard** — CFR KPI, volume/trend charts, top open risk.
2. Open change **#7** — walk the "Why this score" panel (major base + tier-0 systems + past failure on payments-db − overnight mitigation).
3. **Approvals** — approve it with one click (any-of policy), or from a real Slack DM when installed.
4. **Integrations → email simulator** — file a change by "emailing" it; watch it get parsed, scored and filed as a draft with a reply containing the full "why".
5. **Simulator** — drag the window slider; show score, collisions and blast radius moving live.
6. Back on the change: **Start implementing → Mark completed → post-change check** → dashboard CFR updates.

## Real Slack integration (phase 2, week 2)

The demo outbox (`/slack`) stays the source of truth. When a Slack app is installed, every
approval request is additionally DM'd to mapped approvers, and the ✅/❌ buttons in Slack
resolve the change through the same any-of policy as the web app.

1. Create the app from `slack-app-manifest.yml` (api.slack.com/apps → *From an app manifest*).
2. Put `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `SLACK_SIGNING_SECRET` in the environment
   (and `SLACK_REDIRECT_URI=https://<host>/api/integrations/slack/oauth/callback` if not on Render).
3. Set the app's **Interactivity Request URL** to `https://<host>/api/slack/interactions`.
4. Visit `/api/integrations/slack/install` as a workspace admin → consent → the bot token is
   stored in the DB (`settings` table) — no redeploy needed on reinstall.
5. Link approvers: automatic on first Slack action when the workspace email matches the app
   user's email, or manually via `POST /api/users/{id}/slack-link` (admin).

Behavioral guarantees (all tested): invalid signature → 401 + audit entry; Slack unreachable →
delivery error recorded on the outbox row, web approvals keep working; replayed button clicks →
idempotent; unlinked actor → ephemeral "link your account" hint.

## Email-to-change (phase 2, week 3)

An engineer emails the mailbox with **subject = change title** and simple keyword lines in the body:

```
systems: payments-db, orders-api
window: 2026-10-01 22:00 - 23:30
type: major
rollback: restore snapshot pg-14 and repoint the connection string
```

The pipeline parses it, resolves systems (unknown ones reject the email with a helpful reply —
never a guess), scores the risk, files a **DRAFT** (never auto-submits), records an audit row and
replies with the score and the full "why". Safety rules: the same `Message-ID` never files twice,
sender domains can be allowlisted (`EMAIL_ALLOWED_DOMAINS`), the webhook is signature-verified
(`EMAIL_WEBHOOK_KEY`), and **inbound email can never approve anything**.

Setup (all optional — without it, use the simulator on the Integrations page):

1. SendGrid → Inbound Parse → POST to `https://<host>/api/integrations/email/inbound?key=<EMAIL_WEBHOOK_KEY>`.
2. Set `EMAIL_WEBHOOK_KEY` (any random string) and `EMAIL_ALLOWED_DOMAINS` (e.g. `yourcompany.com`) on the host.
3. Outbound sweeps (post-change prompts, daily approval digests, Slack-failure fallbacks) run on
   demand via `POST /api/integrations/email/sweep` or the button on the Integrations page;
   emails land in the auditable outbox (wire real SMTP/SendGrid sending later by swapping one function).

## Deploy-as-change (v0.3, week 1)

Connect a repo on the Integrations page (repo, affected systems, optional auto-submit), then add a
GitHub webhook (*Settings → Webhooks*):

- **URL:** `https://<host>/api/integrations/github/webhook`
- **Secret:** the connection's own secret, or the global `GITHUB_WEBHOOK_SECRET` env var
- **Events:** *Workflow runs* (a `deploy production` workflow) or *Deployments*

A completed production deploy creates a scored draft change with the run linked; with auto-submit
on, risky deploys go to the same Slack/email approval flow as hand-filed changes. When the run
completes, its conclusion (`success`/`failure`) is recorded as the post-change result — the "did it
work?" loop closes itself. Delivery-id idempotency means GitHub retries never duplicate changes.

Use the **simulate** form on the Integrations page to see the pipeline without GitHub.

## Calendar feed (v0.3, week 2)

Every user gets a personal, rotatable .ics feed of visible change windows (submitted / approved /
implementing) and freezes (all-day events): **Integrations → Calendar feed → Enable my calendar
feed**, then paste the URL into Google Calendar (*Other calendars → From URL*) or Outlook
(*Add calendar → Subscribe from web*). Events carry the risk score, class, status, systems and a
deep link; UIDs are stable so updates replace events in place. Rotating the URL kills the old one
(audit-logged). Two-way Google/Outlook write-back lands later in week 2.

## Configuration (all optional)

Copy `backend/.env.example` → `.env`. Highlights:

- `ANTHROPIC_API_KEY` — enables Claude-drafted plans; without it, deterministic template drafts are used.
- `DATABASE_URL` — defaults to SQLite at `data/Ricozchange.db`; use Postgres in production.
- `GATE_BY_DEMO_USER=true` + Clerk vars — real auth via Clerk JWKS; demo mode is single-user.
- `ADMIN_EMAILS` — comma-separated emails that get an **admin account auto-provisioned** on first Clerk sign-in.
- `SLACK_*` — the real Slack integration (see above); all empty = demo outbox only.

## Real sign-in (Clerk, ~10 minutes)

The demo runs in open demo mode (single demo actor, no login). To require real sign-in:

1. **Create the Clerk app** — [dashboard.clerk.com](https://dashboard.clerk.com) → **Create application**. Name it `RicozChange`, enable **Email address** (and Google/GitHub if you like), keep the default sign-in appearance.
2. **Copy four values** from Clerk:
   - **Publishable key** (`pk_test_…`) from *API keys* → used at **build time** by the frontend.
   - **JWKS URL** — `https://<your-instance>.clerk.accounts.dev/.well-known/jwks.json` (shown on the same API keys page).
   - **Issuer** — `https://<your-instance>.clerk.accounts.dev`.
   - **Secret key** (`sk_test_…`) — lets the backend resolve emails from `sub`-only session tokens.
3. **Set them on Render** (web service → Environment):
   `VITE_CLERK_PUBLISHABLE_KEY`, `GATE_BY_DEMO_USER=1`, `CLERK_JWKS_URL`, `CLERK_ISSUER`, `CLERK_SECRET_KEY`, and `ADMIN_EMAILS=your.real@email.com`.
   `VITE_CLERK_PUBLISHABLE_KEY` is a build-time variable — Render's Docker builds pick it up automatically via the Dockerfile `ARG`.
4. **Add your sign-in URLs** in Clerk (*Paths* or *Home → Show all* → customize): sign-in path `/`, sign-up `/sign-up`.
5. **Save** → Render rebuilds → open your demo URL: you'll get the RicozChange sign-in screen, and after signing in with `ADMIN_EMAILS` email #1, your admin account is **created automatically** (audited as `user_provisioned`). Every other person must sign in with an email that matches a seeded user (or you add it to `ADMIN_EMAILS` / the users table).
6. **Rollback is trivial**: remove `VITE_CLERK_PUBLISHABLE_KEY` and set `GATE_BY_DEMO_USER=0` → rebuild → demo mode returns (all data intact).

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest tests/ -q
```

## Smoke-test a deployment

One command verifies any deployment — read-only by default, safe to run against production:

```bash
backend/.venv/Scripts/python scripts/smoke.py https://ricozchange-1y64.onrender.com
# add --write to also run the full workflow round-trip (demo deployments only):
backend/.venv/Scripts/python scripts/smoke.py http://localhost:8600 --write
```

Checks: health, SPA bundle, Slack/email status endpoints, and the auth gate
(a gated deployment reports its 401 as the *correct* answer). `--write` creates
→ submits → approves → completes → post-checks a change, then leaves the audit trail.

## Secret rotation (when you go to production)

- **Clerk:** rotate `CLERK_SECRET_KEY` / keys from the Clerk dashboard → API keys; the JWKS
  URL keeps working across rotation. Test-mode keys (`pk_test_`/`sk_test_`) are fine for demos.
- **Slack:** rotate the signing secret and reinstall via `/api/integrations/slack/install`
  (the bot token lives in the DB `settings` table — reinstall needs no redeploy).
- **Email webhook:** change `EMAIL_WEBHOOK_KEY` and update the SendGrid Inbound Parse URL to match.
- Rate limits protect the public endpoints (Slack/email webhooks: 60/min per IP; sweep: 6/min).

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

# RicozChange — Product PRD (everything built so far)

**For:** the whole team — no prior context needed
**Status:** what exists today, live in production
**Try it:** https://ricozchange-1y64.onrender.com
**Companion docs:** `docs/PHASE2_PRD.md` (the next 4 weeks) · `docs/ROADMAP.md` (the next 3 months)

---

## 1. What is RicozChange?

RicozChange is a web app for IT **change management**: the process a team follows before
anything risky touches production — a database migration, a server upgrade, a config change.

Instead of approvals buried in email threads and meetings, every change is **filed in one
place, scored for risk with clear reasons, approved by the right people, and checked
afterwards** so the team learns from every change.

> **One sentence for your manager:** RicozChange tells you *how risky* a change is, *why*,
> *what it can break*, and gets it *approved in minutes instead of days*.

## 2. The problem it solves

| The old way | The RicozChange way |
|---|---|
| Risk is a gut feeling in a meeting | Every change gets a **risk score with line-by-line reasons** |
| Two teams change the same system on the same night and find out during the incident | The **collision detector** warns at filing time |
| CAB meetings review everything, so everything is slow | **Low-risk changes auto-approve in one click**; only risky ones need people |
| Approvers miss requests in email | Approvals arrive as **Slack DMs with Approve / Reject buttons** |
| Nobody remembers if the last change actually worked | The **post-change check** ("did it work?") feeds a live failure-rate dashboard |

## 3. The life of a change (how the product works)

```
 1. DRAFT        Engineer files a change (web form, CSV import, or seeded demo data)
      │
 2. SCORE        Risk engine scores it 0–100 and shows every reason
      │            (+70 major change, +15 business-critical system, −25 rollback plan …)
 3. CHECK        Collision detector: overlaps with other changes? freeze period? bad timing?
      │
 4. APPROVE      Low risk  → auto fast-track (one click, no meeting)
      │            High risk → approvers get Slack DMs / approval inbox; CAB reviews majors
 5. SCHEDULE     Safe-window finder suggests the best slot around freezes & other changes
      │
 6. IMPLEMENT    Owner runs the change in its window; AI-drafted rollback & test plans help
      │
 7. LEARN        "Did it work?" → success / partial / failed
      │            Results feed the failure-rate (CFR) dashboard…
      └─────────── and future risk scores (same system failed before? score goes up)
```

Every step above is **built and running today**.

## 4. What's built — feature by feature

### The core workflow

| Feature | What it does | Where you see it |
|---|---|---|
| **Change requests** | Create, edit, classify (standard / normal / major / emergency), schedule a window, submit, implement, complete | **Changes** page |
| **Explainable risk score** | 0–100 score where **every point has a reason** ("+15: payments-db is tier-0"). No black box — this is the product's core differentiator | Change detail → "Why this score" |
| **Collision detector** | Warns when another change touches the same system in the same window | Change detail + Simulator |
| **Freeze calendar** | Blocked periods (financial close, holidays) where changes are rejected or flagged | **Freezes** page |
| **Safe-window finder** | Suggests the best slots, avoiding freezes and neighbouring changes | Change form |
| **Auto fast-track** | Standard changes scoring under 25 approve in one click — no meeting | Any standard change |
| **Post-change check** | After the window: "did it work?" → success / partial / failed | Change detail |
| **CFR dashboard** | Live change-failure-rate KPI + 8-week charts | **Dashboard** page |

### Approvals & CAB

| Feature | What it does | Where |
|---|---|---|
| **Approval inbox** | All pending approvals with score, window, systems, risk reasons and one-click decisions | **Approvals** page |
| **Slack approvals (real)** | OAuth app install → approvers get **real DMs** with the full "why"; Approve/Reject buttons in Slack resolve the change; buttons are idempotent (double-clicks can't double-apply); callbacks are signature-verified | Slack workspace + **Integrations** page |
| **Slack demo outbox** | Renders the exact message payload — still the source of truth and delivery audit when Slack isn't connected | Part of Approvals |
| **CAB** | Schedule meetings, build agendas, vote, record decisions; a decision-outcomes donut shows the history | **CAB** page |
| **Any-of policy** | Change is approved when **any assigned approver** decides; the others' requests auto-close (no chasing) | Everywhere |

### Understanding risk (the "wow" features)

| Feature | What it does | Where |
|---|---|---|
| **Change Simulator** | Drag sliders (change type, window, systems…) and watch the score, collisions and blast radius react **live**. Best demo in the product | **Simulator** page |
| **Blast-radius map** | Interactive dependency graph — a change lights up everything it can take down | **Blast radius** page + every change detail |
| **AI-drafted plans** | Claude drafts the rollback plan, test checklist and stakeholder comms from the change details. **Human-approved, never auto-applied** | Change detail → "AI drafting" |
| **Dashboard charts** | Change volume (stacked bars by class), failure-rate trend line, class-mix donut, most-changed systems heat bars | **Dashboard** |

### Trust & admin

| Feature | What it does | Where |
|---|---|---|
| **Audit log** | Append-only trail: who did what, when — searchable, with a 14-day activity sparkline. Entries are written once and never edited | **Audit log** page |
| **Real sign-in** | Google / email login via Clerk. First sign-in with an `ADMIN_EMAILS` email auto-creates your admin account | Every page |
| **Roles** | engineer / approver / manager / admin — enforced on the **server**, not just hidden in the UI (see §6) | Everywhere |
| **Integrations page** | Live status of Slack and sign-in, plus the install button | **Integrations** page |
| **CSV import** | Bring your existing change backlog — the switching-cost killer | Changes page |

## 5. The rules the app enforces (all tested)

- You can **never approve your own change**.
- Engineers can create and submit changes but **cannot approve anything**.
- Every action lands in the audit log with a real user identity — denials included.
- Slack button clicks are **idempotent**; invalid signatures get 401 + an audit entry.
- Slack down? Delivery failures are recorded; **web approvals keep working**.
- Without a rollback plan, the risk score says so (and it costs you points).

## 6. Who can do what (roles)

| Action | Engineer | Approver | Manager | Admin |
|---|---|---|---|---|
| View dashboards, changes, audit | ✅ | ✅ | ✅ | ✅ |
| Create / edit / submit own change | ✅ | ✅ | ✅ | ✅ |
| Approve / reject (assigned to them) | ❌ | ✅ | ✅ | ✅ |
| Vote in CAB | ❌ | ✅ | ✅ | ✅ |
| Run CAB, manage freezes, CSV import | ❌ | ❌ | ✅ | ✅ |
| Users, roles, settings | ❌ | ❌ | ❌ | ✅ |

## 7. The tech, in plain words

| Piece | What we use | Why |
|---|---|---|
| UI | React + TypeScript + Tailwind, 11 pages | Fast to build, easy to hire for, looks like a real product |
| API | FastAPI (Python), 53 automated tests | The brain: scoring, workflow, permissions |
| Database | SQLite locally → managed Postgres on Render | Free to start, production-grade when it matters |
| Sign-in | Clerk (Google / email) | Don't build auth yourself; SSO-ready later |
| Chat | Slack app (OAuth + signed callbacks) | Approvals where approvers already are |
| AI | Claude API (optional) | Drafts plans; falls back to templates without a key |
| Hosting | Render, auto-deploys on every push to `main` | Zero-ops demo |

**Where things live in the repo:** `backend/ricozchange/` — `risk_engine.py` (scoring,
collisions, safe windows), `services.py` (workflow state machine + seeding), `models.py`
(15 tables), `auth.py` (Clerk + demo mode), `slack_app.py` + `notifications.py` (Slack),
`main.py` (routes). `frontend/src/pages/` — one file per page. `tests/` — end-to-end API tests.

**Run it locally:** `README.md` quickstart (backend + frontend, seeds itself with demo data
including one risky pending change ready to approve).

## 8. Current status (honest)

- ✅ Live public demo on Render; sign-in gated with real Clerk auth; admin = `dwivedyarvind67@gmail.com`
- ✅ 53 backend tests passing; every push to `main` auto-deploys
- ✅ Demo data reseeds itself on an empty database — the demo can't be broken for long
- ⚠️ Email-to-change, CI pipeline and error tracking are **not built yet** — first items of Phase 2 (see `docs/PHASE2_PRD.md`)

## 9. What's next (very short version)

1. **Phase 2 (4 weeks):** email-to-change, CI + E2E tests, error tracking, Slack polish.
2. **v0.3 "Operations":** deploys auto-become changes (GitHub webhook), calendar sync, Teams, DORA analytics.
3. **v1.0 "Pilot":** compliance pack (audit export, CAB minutes), billing, SSO hardening — sellable.

Details and effort estimates: `docs/ROADMAP.md`.

## 10. Glossary (for non-ITIL folks)

- **CAB** — Change Advisory Board: the group that reviews risky changes.
- **CFR** — Change Failure Rate: % of changes that caused a problem. Lower is better; tracked on the dashboard.
- **Change window** — the approved time slot to do the work.
- **Freeze** — a period when changes are blocked (financial close, holidays).
- **Blast radius** — everything that breaks if this change goes wrong.
- **Tier-0** — business-critical system (payments, checkout). Touching one costs risk points.
- **Rollback plan** — the pre-written "undo" steps if the change fails.
- **Fast-track** — auto-approval for pre-approved, low-risk standard changes.

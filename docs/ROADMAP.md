# RicozChange — Next-Level Roadmap

**Status:** approved · **Horizon:** ~3 months to a pilot-ready v1.0 · **Team:** 1 dev + AI agents
**Baseline today:** MVP live — explainable risk scoring, collision detector, safe-window finder, CAB,
Slack-style outbox, post-change checks, CFR dashboard. Phase-2 week 1 shipped: server-side role
enforcement (owner can't approve own change, every denial audit-logged) and an Alembic migration
baseline with auto-stamp.

---

## 0. Where we are — honest inventory

| Area | State |
|---|---|
| Core workflow (create → score → approve → implement → learn) | ✅ Live, 23 passing tests |
| Explainable risk engine (rules, "why" panel, collisions, freezes, safe windows) | ✅ Live |
| Deploy | ✅ Render auto-deploys every push to `main` |
| Auth backend | ✅ Role matrix enforced server-side; denial auditing; Alembic baseline |
| Auth frontend | ⚠️ Demo mode only — one hardcoded user ("demo mode" banner) |
| Slack | ⚠️ Demo outbox renders the exact message payloads; no real workspace |
| Email | ❌ Nothing |
| CI | ❌ Tests run locally only — a red push still deploys |
| Observability | ❌ No error tracking, no uptime alerts |

The next level is closing the gap between "impressive demo" and "tool a real team runs its week on" —
then making it sellable.

---

## 1. The version ladder

```
v0.1  TODAY          Working MVP, public demo, permissions enforced server-side
v0.2  "Real team"    Real identity everywhere · Slack DMs · email-to-change      (4 weeks)
v0.3  "Operations"   Deploy-as-change · calendar sync · Teams · DORA analytics  (4 weeks)
v1.0  "Pilot"        Compliance pack · billing & seats · hardening · support    (4–6 weeks)
```

Each version has one demo gate that either passes or the version isn't done.

---

## 2. v0.2 — "Real team": authentication everywhere (weeks 1–4)

This is the version where every action is attributable to a real person, on every surface.

### 2.1 Full authentication story (weeks 1–2)

**Frontend (Clerk):**
- `ClerkProvider` + `<SignIn/>` via `VITE_CLERK_PUBLISHABLE_KEY`; when the key is absent the app
  falls back to demo mode (the public demo URL keeps working untouched).
- Protected routes: the UI hides actions the server would 403, but never trusts itself —
  the server remains the only authority.
- Identity surfaces: real name/avatar in the sidebar, role badge, "signed in as" replaces
  the demo banner.

**Backend (already half-built):**
- Clerk JWT verification (`auth.py`) becomes the default path; `GATE_BY_DEMO_USER=true`
  keeps demo/local/test mode.
- Auto-provisioning: first login creates the `users` row (`clerk_id` = JWT `sub`,
  role `engineer`); admin promotes. No manual user seeding for new teammates.
- **Admin user-management page**: list users, change roles, unlink — the only place roles change,
  fully audit-logged.
- Every audit entry now carries the real user (actor = authenticated identity, not "demo actor").

**Slack identity (bridges to 2.2):**
- `users.slack_id` column; auto-link on first Slack action by email match, with an
  ephemeral "link your account" fallback for mismatches.
- Approvals from Slack act **as the mapped user** — the audit trail can't tell a web approval
  from a Slack one except by `source`.

**Acceptance criteria**
1. Two browsers, two real accounts: the engineer cannot approve (403, audit-logged); the owner
   cannot approve their own change.
2. A brand-new teammate logs in with Google and appears as `engineer` with zero manual seeding.
3. Demo mode (no Clerk keys) still passes the full existing suite — public demo unaffected.
4. Every audit row shows a real user identity.

### 2.2 Real Slack integration (weeks 2–3)

- App manifest (`chat:write`, `im:read`, `im:history`, `users:read`, `users:read.email`;
  interactive components).
- OAuth install: `GET /api/integrations/slack/install` → Slack consent → callback exchanges the
  code and stores the bot token (DB `settings` row — reinstall needs no redeploy).
- Outbound: when `queue_approval_requests` runs, DMs go out via `chat.postMessage` to mapped
  approvers — score, window, systems, and the "why" inline. The DB outbox row stays the
  source of truth and delivery audit (`sent_at`, `slack_ts`, error).
- Inbound: `POST /api/slack/interactions` verifies `X-Slack-Signature` (HMAC ±5 min), resolves
  the action → existing `record_approval` (any-of policy), then `chat.update` on the message.
  Duplicate clicks are idempotent; already-acted messages answer with a friendly ephemeral note.
- Slack outage → outbox marks delivery failed; web approvals keep working.

**Demo gate:** approve a real change from a phone in Slack in under 30 seconds; replayed clicks
never double-apply; invalid signature → 401 logged.

### 2.3 Email-to-change (week 4)

- SendGrid Inbound Parse → `POST /api/integrations/email/inbound` (signature-verified, allowlisted
  domains, dedupe by `Message-ID`).
- Deterministic keyword parser (`systems:`, `window:`, `type:`, `rollback:`); unparseable mail
  files nothing and replies with help — never silent failure.
- Inbound email can only file a **draft**; humans submit. No approvals by email.
- Outbound sweeps (FastAPI lifespan, no new infra): approval digests, "did it work?" prompts,
  Slack-failure fallback emails.

**Demo gate:** file a change entirely from a phone email client; same email twice files one change.

### 2.4 Cross-cutting (starts week 1, runs forever)
- **CI:** GitHub Actions — pytest on every push; frontend build check.
- **E2E smoke:** Playwright against the public URL (login → create → approve → complete).
- **Observability:** Sentry free tier + Render health notifications.

**Estimated effort:** ~25 dev-days.

---

## 3. v0.3 — "Operations": integration depth (weeks 5–8)

The theme: RicozChange stops being something people fill in and becomes infrastructure
that watches the deployment pipeline.

1. **Deploy-as-change (the flagship).** GitHub Actions webhook: a production deploy auto-creates
   the change request, links the commit/PR, and records the outcome from deploy status.
   Engineers get risk scoring and collision detection on code deploys with zero data entry.
2. **Calendar sync.** Freeze windows and change windows on Google Calendar / Outlook (read-only
   subscribe out, OAuth write in). Kills the "what freeze?" class of mistakes.
3. **Microsoft Teams parity.** Same approval cards via Bot Framework — opens the Windows-heavy
   enterprise half of the market.
4. **Analytics.** DORA-style metrics: CFR, lead time to approve, MTTR by team/system;
   exportable CSV. This is the dashboard a head of engineering screenshots for their boss.
5. **Scale niceties:** full-text search over changes, saved views, bulk window shifts,
   dependency-graph editor for the blast-radius map.

**Demo gate:** push to `main` on a sample repo → a scored change appears, approved via Slack,
outcome recorded from the deploy — with no human filling any form.

**Estimated effort:** ~22 dev-days.

---

## 4. v1.0 — "Pilot": sellable (weeks 9–14)

The theme: a stranger can pay, onboard, and pass their security review.

1. **Compliance pack** — the wedge for regulated buyers: audit export (CSV/PDF with hash chain),
   auto-generated CAB minutes, SOC2-style evidence report ("who approved what, when, why").
2. **Billing & seats** (Stripe): per-seat plans, plan gating, trial logic.
3. **SSO hardening:** SAML via Clerk for enterprise, session policies, 2FA enforcement.
4. **Data discipline:** backups + restore drill, retention policy, per-workspace data isolation.
5. **Security hardening:** rate limits on all webhooks, signing-secret rotation, dependency
   scanning, a self-hosted pen-test pass.
6. **Onboarding wizard:** connect Slack + email + GitHub in one guided flow; CSV importer for
   the existing change backlog (the switching-cost killer).
7. **Support runbook + status page** — you're now an operator.

**Demo gate:** a pilot tenant signs up, connects Slack/GitHub, files changes three ways
(web, email, deploy), exports an audit pack — without you touching anything.

**Estimated effort:** ~28 dev-days.

---

## 5. Effort and timeline summary

| Version | Duration | Effort | Hiring trigger |
|---|---|---|---|
| v0.2 Real team | weeks 1–4 | ~25 dev-days | none |
| v0.3 Operations | weeks 5–8 | ~22 dev-days | consider part-time frontend help |
| v1.0 Pilot | weeks 9–14 | ~28 dev-days | yes — support + sales coverage |

## 6. Top risks and mitigations

| Risk | Mitigation |
|---|---|
| Clerk/Slack OAuth edge cases eat week 2 | Build the demo-mode fallback first; every feature degrades gracefully without keys |
| Webhook abuse on the public URL | Signature verification everywhere, allowlists, rate limits (v0.2 start, v1.0 hardening) |
| Scope creep from "enterprise" asks | The ladder above is the contract; anything new goes to the deferred list |
| Solo-developer bus factor | CI + E2E + migrations discipline make the codebase hand-off ready |
| Free-tier Postgres expiry (30 days) on Render | Move to a paid/starter DB before v1.0 pilot; test the restore drill |

## 7. Metrics that decide "is it working"

30 days after each rollout:
- v0.2: ≥ 80% of approvals decided from Slack; median approval latency < 1 h; ≥ 25% of changes
  filed by email; 100% of actions attributable to a real user.
- v0.3: ≥ 30% of changes auto-created from deploys; time-to-file < 30 s.
- v1.0: 3 pilot tenants active; onboarding-to-first-approved-change < 1 day; zero unauthorized
  actions; first paid conversion.

## 8. Deliberately deferred

Multi-workspace Slack, Jira/ServiceNow two-way sync, learned ML risk weights, mobile push,
change templates marketplace, on-prem — none blocks a paying pilot; each gets a roadmap note.

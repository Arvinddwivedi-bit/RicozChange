# RicozChange — v0.3 "Operations" PRD

**Status:** draft for review · **Timeline:** 4 weeks · **Team:** 1 dev + AI agents
**Baseline:** v0.2 complete (phase 2 shipped) — Clerk sign-in with server-enforced roles, real Slack
approvals (OAuth, signed callbacks, idempotent buttons), email-to-change with automated sweeps
(post-change prompts, digests, Slack-failure fallbacks), rate limiting, background sweep loop,
67 passing tests, `scripts/smoke.py` deployment verifier.

---

## 1. Why v0.3 exists

v0.2 made RicozChange something a real team can run its week on. v0.3 makes it
**infrastructure**: the product stops being a place people *fill in* and becomes a system that
*watches the deployment pipeline*, talks to the calendars people already live in, meets Windows-heavy
enterprises on Microsoft Teams, and produces the metrics a head of engineering screenshots for
their boss.

The four features, one per week:

1. **Deploy-as-change** — a production deploy auto-creates the change request. Zero data entry.
2. **Calendar sync** — freezes and change windows live on the calendars people already check.
3. **Microsoft Teams** — same approval cards as Slack, for the enterprise half of the market.
4. **DORA-style analytics** — CFR, approval latency, MTTR by team/system, exportable.

## 2. Goals and non-goals

**Goals**
- A push to `main` on a connected repo becomes a scored, collision-checked change request with
  no human filling any form — and the deploy status records the outcome.
- Freeze windows subscribe-able as an .ics feed; two-way write to Google Calendar / Outlook.
- Teams approval cards with the same any-of policy, identity mapping and audit trail as Slack.
- A metrics dashboard (CFR, lead time to approve, MTTR, volume) with CSV export.

**Non-goals (explicitly deferred)**
- Multi-workspace Slack, Jira/ServiceNow sync, learned ML risk weights, mobile push,
  billing/seats and the compliance pack (those are v1.0), on-prem installs.

## 3. Feature 1 — Deploy-as-change (week 1, the flagship)

### User stories
- As an engineer, when I deploy to production from GitHub Actions, a change request appears with
  the commit/PR linked — I never fill the form.
- As an approver, the auto-created change goes through the same scoring, collision detection and
  (if risky) the same Slack/email approval flow as a hand-filed change.
- As an owner, when the deploy job finishes, the change's outcome (success/failed) is recorded
  from the deploy status — feeding CFR automatically.

### Technical design
- `POST /api/integrations/github/webhook` — signature-verified (HMAC `X-Hub-Signature-256`,
  reuse `rate_limit.webhook_limiter`), `workflow_run` / `deployment` events only.
- Repo connection table (`github_connections`: repo, default systems, auto-submit threshold,
  secret) with an admin UI on the Integrations page.
- Mapping rules: deploy env `production` → change type from changed paths / commit scope
  (fallback `normal`); deploy ref + run URL → change description; deployer email → owner via
  the existing email matching.
- Deploy completes → `record_post_change(success|failed)` from the `workflow_run` conclusion —
  the "did it work?" loop closes itself for deploys.
- Idempotency: `delivery_id` unique per event (same pattern as email `Message-ID`).
- Human-filed changes still win: a deploy matching an open change on the same systems links to
  it instead of creating a duplicate.

### Acceptance criteria
1. Push to a connected repo → change created within 10 s, scored, systems attached, owner mapped.
2. Risky auto-change → approvers get the same Slack DM with the "why".
3. Deploy failure → `post_change_result=failed` recorded; CFR dashboard moves.
4. Replayed webhook delivery → no duplicate change.
5. Invalid signature → 401 + audit entry.

## 4. Feature 2 — Calendar sync (week 2)

### User stories
- As a manager, my freeze windows appear on my Google/Outlook calendar automatically.
- As an engineer, I subscribe to the change calendar read-only (one URL, no auth drama).
- As an approver, I can see which changes are scheduled this week without opening the app.

### Technical design
- **Read-only out (week 2, day 1):** `GET /api/calendar/changes.ics` — RFC 5545 feed of
  change windows + freezes, token-authenticated per user (`users.calendar_token`), refreshable.
  Zero external dependencies — this alone delivers most of the value.
- **Two-way write (rest of the week):** Google Calendar API + Microsoft Graph (OAuth via Clerk
  identity, tokens in the `settings` table — same pattern as the Slack bot token). Changes create
  calendar events; freezes create all-day events. Conflict errors never block the workflow
  (logged, retried by the existing sweep pattern).
- Window changes propagate: PATCH a change → update the linked event (store `calendar_event_id`).

### Acceptance criteria
1. `.ics` URL subscribes in Google Calendar and Outlook; events show window + risk.
2. Rotating the token kills the old URL (audit-logged).
3. A submitted change appears in the connected calendar within 60 s.
4. Calendar outage → nothing in the change workflow breaks.

## 5. Feature 3 — Microsoft Teams (week 3)

### User stories
- As a Teams-shop approver, I get approval cards as DMs with score + "why" and Approve/Reject
  buttons, exactly like Slack.
- As an admin, I install the app once from the Integrations page.

### Technical design
- Azure Bot registration + Bot Framework; `POST /api/teams/interactions` with
  `Authorization: Bearer` validation against the published bot App ID (Azure OpenID metadata,
  cached) — the Slack-signature pattern ported.
- Outbound: proactive messages via bot token; reuse the existing outbox shape
  (`Notification.kind="teams"`) so Approvals-page rendering works unchanged.
- Identity: `users.teams_id`; same email auto-link + ephemeral fallback as Slack.
- Any-of policy, idempotency keys, delivery audit: literally the same service calls — only the
  transport differs. Teams outage → same fallback chain (email already built).

### Acceptance criteria
1. Approve from a phone in Teams in < 30 s; duplicate clicks never double-apply.
2. Both approvers' cards close correctly under any-of (one approves, the other is superseded).
3. Invalid bot token → 401 + audit entry; Teams outage → email fallback fires.

## 6. Feature 4 — DORA-style analytics (week 4)

### User stories
- As a head of engineering, I see CFR, median approval latency and MTTR per team/system for any
  date range, and export it.
- As a manager, I see volume and risk mix trends, and the systems with the worst failure record.

### Technical design
- `GET /api/analytics?from&to&group_by=system|team` computing: **CFR** (exists — extend),
  **lead time to approve** (created→approved), **approval latency** (submitted→decided),
  **MTTR** (for failed changes: window_end → post_change_result=success on the follow-up),
  **change volume**, **risk mix**. All from existing tables — no schema change beyond indexes.
- Frontend: an **Analytics** page under Operate using the existing chart components
  (donut, stacked bars, trend line); date-range picker; CSV export endpoint
  (`GET /api/analytics/export.csv`) reusing the importer's CSV conventions.
- Aggregate-only for non-admins (team-level visibility rules come with v1.0 workspaces).

### Acceptance criteria
1. Date-range + group-by switch updates every card; numbers match the seeded history.
2. CSV opens cleanly in Excel (headers + ISO dates).
3. All four key metrics computed from real data with zero manual entry.

## 7. Week-by-week plan

| Week | Deliverable | Demo gate |
|---|---|---|
| 1 | GitHub webhook, repo connections, auto-scoring, deploy-outcome loop | Push to a sample repo → scored change appears → approve from Slack → deploy status records the outcome, no form touched |
| 2 | `.ics` feeds (day 1), Google/Outlook two-way sync, token rotation | Change appears in a real calendar within 60 s; old token dies on rotation |
| 3 | Teams app, approval cards, identity mapping, fallback chain | Approve from Teams on a phone in < 30 s; duplicates idempotent |
| 4 | Analytics API + page + CSV export, hardening, E2E smoke extension, docs | Manager demo: push → auto-change → Teams approval → CFR moves on the analytics page |

Estimated effort: W1 ~7 dev-days, W2 ~5, W3 ~6, W4 ~4 (solo + AI agents, includes tests).

## 8. Risks

| Risk | Mitigation |
|---|---|
| GitHub event variety (rename, re-run, skipped) | Only two event types; unique `delivery_id`; unknown payloads rejected with 4xx, never 500 |
| Calendar APIs eat the week | Ship the .ics feed on day 1 — value exists even if OAuth write slips; two-way is a bonus |
| Azure bot registration friction (app tenant, consent) | Start the registration week 1 in parallel; demo can use the Bot Framework Emulator until tenant consent lands |
| Metric definitions argued about | Fix definitions in this PRD (above); document formulas on the Analytics page itself |
| Webhook abuse surface grows | Every new webhook: signature verification + the existing rate limiter + idempotency, same as email |

## 9. Success metrics (30 days after rollout)

- ≥ 30% of changes auto-created from deploys; time-to-file < 30 s for deploy changes
- ≥ 1 external calendar subscriber per team; zero workflow incidents caused by calendar outages
- ≥ 20% of approvals decided from Teams (in Teams-shops)
- The analytics page becomes the most-screenshotted page in manager demos

## 10. Deliberately deferred

Billing/seats, compliance pack, SSO hardening, workspaces with per-team visibility, ML risk
weights, Jira/ServiceNow sync, mobile push — v1.0 candidates, none block the operations story.

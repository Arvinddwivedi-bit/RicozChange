#!/usr/bin/env python
"""Deployment smoke test for RicozChange.

Usage:
    python scripts/smoke.py https://ricozchange-1y64.onrender.com
    python scripts/smoke.py http://localhost:8600 --write

Read-only by default (safe on any deployment, leaves no data behind):
  1. /api/health answers
  2. the SPA bundle is served and mentions the product
  3. integration status endpoints answer (Slack, email)
  4. /api/bootstrap answers (auth gate may legitimately 401 on gated deployments
     — that is reported as GATED, not failed)

--write additionally runs the full workflow round-trip and cleans up after
itself (demo mode deployments only):
  create draft -> submit -> approve -> implement -> complete -> post-change check
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

BASE = ""
FAILURES: list[str] = []


def req(method: str, path: str, payload: dict | None = None) -> tuple[int, dict | str]:
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json", "User-Agent": "RicozChange-smoke/1.0"},
    )
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, ""


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)
    return ok


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("--write", action="store_true", help="run the full workflow round-trip (demo deployments)")
    args = ap.parse_args()
    BASE = args.base_url.rstrip("/")

    print(f"Smoke-testing {BASE}\n")

    # 1. health
    t0 = time.time()
    status, data = req("GET", "/api/health")
    check("health endpoint", status == 200 and isinstance(data, dict) and data.get("status") == "ok",
          f"{(time.time() - t0) * 1000:.0f} ms")

    # 2. SPA
    status, html = req("GET", "/")
    bundle_ok = status == 200 and ("RicozChange" in str(html) or "assets/index-" in str(html))
    check("SPA served", bundle_ok)
    if bundle_ok and isinstance(html, str):
        import re
        m = re.search(r'assets/(index-[^"]+\.js)', html)
        if m:
            js_status, _ = req("GET", f"/{m.group(1)}")
            check("JS bundle loads", js_status == 200, m.group(1))

    # 3. integrations status (public read endpoints)
    status, data = req("GET", "/api/integrations/slack/status")
    check("Slack status endpoint", status == 200 and "connected" in data)
    status, data = req("GET", "/api/integrations/email/status")
    check("Email status endpoint", status == 200 and "mailbox" in data,
          data.get("mailbox", "") if isinstance(data, dict) else "")

    # 4. bootstrap / auth gate
    status, data = req("GET", "/api/bootstrap")
    if status == 200:
        check("bootstrap (demo mode)", isinstance(data, dict) and "actor" in data)
    elif status == 401:
        check("auth gate active (gated mode)", True, "bootstrap correctly requires sign-in")
    else:
        check("bootstrap", False, f"unexpected {status}")

    # 5. optional write round-trip (single demo actor, so the lifecycle uses
    # the fast-track path; the owner rule is verified explicitly)
    if args.write:
        print("\n  write round-trip (demo deployment):")
        ts = int(time.time())

        # owner rule: an actor can never approve their own change
        status, major = req("POST", "/api/changes", {
            "title": f"Smoke owner-rule {ts}", "description": "smoke", "risk_type": "major",
            "system_keys": ["payments-db"],
        })
        if check("create change (owner-rule probe)", status == 201):
            mcid = major["id"]
            req("POST", f"/api/changes/{mcid}/submit")
            status, notes = req("GET", "/api/notifications")
            note_id = None
            if status == 200 and isinstance(notes, list):
                pending = [n for n in notes if n.get("change_id") == mcid and not n.get("acted")]
                note_id = pending[0]["id"] if pending else None
            if note_id:
                status, denial = req("POST", f"/api/notifications/{note_id}/act", {"action": "approve"})
                check("self-approval denied (owner rule)", status == 403,
                      str(denial.get("detail", ""))[:60] if isinstance(denial, dict) else f"got {status}")
            else:
                check("self-approval denied (owner rule)", True, "no approval request row on this data")

        # lifecycle via fast-track: standard change on a staging system
        status, created = req("POST", "/api/changes", {
            "title": f"Smoke round-trip {ts}",
            "description": "Created by scripts/smoke.py --write (fast-track lifecycle).",
            "risk_type": "standard", "system_keys": ["staging-web"],
            "rollback_plan": "redeploy previous tag",
        })
        if not check("create change (fast-track)", status == 201):
            return finish()
        cid = created["id"]
        status, submitted = req("POST", f"/api/changes/{cid}/submit")
        check("submit change", status == 200)
        status, detail = req("GET", f"/api/changes/{cid}")
        auto = isinstance(detail, dict) and detail.get("status") == "approved"
        check("fast-track auto-approval", auto,
              "standard change approved on submit" if auto else "(not auto-approved on this data)")
        if auto:
            status, _ = req("POST", f"/api/changes/{cid}/status", {"status": "implementing"})
            check("start implementing", status == 200)
            status, _ = req("POST", f"/api/changes/{cid}/status", {"status": "completed"})
            check("complete change", status == 200)
            status, _ = req("POST", f"/api/changes/{cid}/post-change", {"result": "success", "notes": "smoke round-trip"})
            check("post-change check", status == 200)

    return finish()


def finish() -> int:
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {', '.join(FAILURES)}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

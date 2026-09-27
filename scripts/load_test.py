#!/usr/bin/env python
"""Load test for RicozChange — simulates up to N concurrent users.

Usage:
    backend/.venv/Scripts/python scripts/load_test.py http://127.0.0.1:8600 --users 1000
    backend/.venv/Scripts/python scripts/load_test.py https://host --users 10 --seconds 30  # probe

What a "user" does: a weighted journey of real API calls a real user makes —
bootstrap, changes list, change detail, notifications, dashboard, integration
statuses, calendar feed. Writes are opt-in (--write) so a read-only run leaves
no data behind.

Reports: requests, RPS, error count by kind, latency p50/p90/p99/max, and any
non-2xx responses observed. Threads (not asyncio) keep the profile realistic
for connection handling and avoid Event-loop skew at high concurrency.
"""
from __future__ import annotations

import argparse
import http.client
import json
import random
import statistics
import sys
import threading
import time
import urllib.parse

BASE_HOST = ""
BASE_PORT = 0
BASE_TLS = False
BASE_PATH_PREFIX = ""
STOP = threading.Event()
LOCK = threading.Lock()

RESULTS = {"count": 0, "errors": 0, "latencies": [], "status_codes": {}, "error_kinds": {}}
WRITES = {"created": 0, "failed": 0}


_tls_ctx = None


def _connect() -> http.client.HTTPConnection:
    if BASE_TLS:
        import ssl
        global _tls_ctx
        if _tls_ctx is None:
            _tls_ctx = ssl.create_default_context()
        return http.client.HTTPSConnection(BASE_HOST, BASE_PORT, context=_tls_ctx, timeout=15.0)
    return http.client.HTTPConnection(BASE_HOST, BASE_PORT, timeout=15.0)


def req(conn: http.client.HTTPConnection, method: str, path: str, payload: dict | None = None):
    """One request over a persistent connection (browser-like keep-alive).
    Returns (status|0, ms, error|None); reconnects once on stale connections."""
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json", "User-Agent": "RicozChange-loadtest/1.0"}
    t0 = time.perf_counter()
    for attempt in (0, 1):
        try:
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            resp.read()
            ms = (time.perf_counter() - t0) * 1000
            if resp.will_close:
                conn.close()
                new = _connect()
                conn.__dict__.update(new.__dict__)
            return resp.status, ms, None if resp.status < 400 else f"HTTP {resp.status}"
        except (http.client.HTTPException, OSError) as e:
            try:
                conn.close()
            except Exception:
                pass
            if attempt == 0:
                new = _connect()
                conn.__dict__.update(new.__dict__)
                continue
            return 0, (time.perf_counter() - t0) * 1000, type(e).__name__
    return 0, (time.perf_counter() - t0) * 1000, "unreachable"


def record(status: float, ms: float, err: str | None) -> None:
    with LOCK:
        RESULTS["count"] += 1
        RESULTS["latencies"].append(ms)
        if err:
            RESULTS["errors"] += 1
            RESULTS["error_kinds"][err] = RESULTS["error_kinds"].get(err, 0) + 1
        else:
            code = str(int(status))
            RESULTS["status_codes"][code] = RESULTS["status_codes"].get(code, 0) + 1


# Weighted read mix — what real users' browsers actually hit.
READ_JOURNEYS = [
    ("bootstrap", "GET", "/api/bootstrap", 18),
    ("changes", "GET", "/api/changes", 20),
    ("dashboard", "GET", "/api/dashboard", 12),
    ("notifications", "GET", "/api/notifications", 14),
    ("health", "GET", "/api/health", 8),
    ("slack_status", "GET", "/api/integrations/slack/status", 5),
    ("email_status", "GET", "/api/integrations/email/status", 5),
    ("github_status", "GET", "/api/integrations/github/status", 5),
    ("change_detail", "GET", "__detail__", 8),
]


def _detail_path(conn) -> str:
    s, _, _ = req(conn, "GET", "/api/changes")
    if s == 200:
        try:
            conn.request("GET", "/api/changes", headers={"User-Agent": "RicozChange-loadtest/1.0"})
            data = json.loads(conn.getresponse().read())
            rows = data if isinstance(data, list) else data.get("items", [])
            if rows:
                return f"/api/changes/{random.choice(rows)['id']}"
        except Exception:
            pass
    return "/api/changes/1"


def user_worker(idx: int, seconds: float, write: bool) -> None:
    rnd = random.Random(idx)
    conn = _connect()
    deadline = time.time() + seconds
    detail_cache = None
    while time.time() < deadline and not STOP.is_set():
        pick = rnd.choices(READ_JOURNEYS, weights=[w for _, _, _, w in READ_JOURNEYS])[0]
        name, method, path, _ = pick
        if path == "__detail__":
            if detail_cache is None:
                detail_cache = _detail_path(conn)
            path = detail_cache
        status, ms, err = req(conn, method, path)
        record(status, ms, err)

        if write and rnd.random() < 0.02:
            status, ms, err = req(conn, "POST", "/api/changes", {
                "title": f"Load-user-{idx}-{rnd.randint(1, 10**6)}",
                "description": "Created by load test (--write).",
                "risk_type": rnd.choice(["standard", "normal", "major"]),
                "system_keys": ["staging-web"],
                "rollback_plan": "redeploy previous tag",
            })
            record(status, ms, err)
            if status == 201:
                WRITES["created"] += 1
            else:
                WRITES["failed"] += 1
        time.sleep(rnd.uniform(0.05, 0.3))  # think time
    try:
        conn.close()
    except Exception:
        pass


def main() -> int:
    global BASE_HOST, BASE_PORT, BASE_TLS
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("--users", type=int, default=1000)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--ramp", type=float, default=3.0, help="seconds to ramp up over")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--shard", default="0/1", help="this shard: i/n (users split across n client processes)")
    ap.add_argument("--quiet", action="store_true", help="shard mode: print one JSON line at the end")
    args = ap.parse_args()
    shard_idx, shard_n = (int(x) for x in args.shard.split("/"))
    u = urllib.parse.urlparse(args.base_url if (urllib_parse := __import__("urllib.parse")) else args.base_url)
    BASE_HOST = u.hostname or "127.0.0.1"
    BASE_PORT = u.port or (443 if u.scheme == "https" else 80)
    BASE_TLS = u.scheme == "https"
    label = args.base_url.rstrip("/")

    print(f"Load test: {args.users} users, {args.seconds}s, ramp {args.ramp}s, writes={'on' if args.write else 'off'}")
    print(f"Target: {label} (keep-alive connections)\n")

    # sanity pre-flight
    conn = _connect()
    s, _, err = req(conn, "GET", "/api/health")
    if s != 200:
        print(f"Pre-flight failed: /api/health -> {s} {err}")
        return 2
    print("Pre-flight OK. Starting...\n")

    threads = []
    t0 = time.perf_counter()
    per_shard = args.users // shard_n
    my_count = per_shard + (1 if shard_idx < args.users % shard_n else 0)
    for j in range(my_count):
        i = shard_idx * per_shard + j  # globally unique user id
        th = threading.Thread(target=user_worker, args=(i, args.seconds, args.write), daemon=True)
        threads.append(th)
        th.start()
        if args.ramp and j % max(1, my_count // 20) == 0:
            time.sleep(args.ramp / 20)

    for th in threads:
        th.join(args.seconds + args.ramp + 30)
    wall = time.perf_counter() - t0

    lat = sorted(RESULTS["latencies"])
    n = len(lat)

    if args.quiet:
        def pct_q(p):
            return lat[min(n - 1, int(n * p))] if n else 0.0
        print(json.dumps({
            "shard": f"{shard_idx}/{shard_n}", "requests": n, "errors": RESULTS["errors"],
            "error_kinds": RESULTS["error_kinds"], "p50": round(pct_q(0.5), 1),
            "p99": round(pct_q(0.99), 1), "max": round(lat[-1], 1) if n else 0,
            "writes": WRITES["created"],
        }))
        return 0 if RESULTS["errors"] == 0 else 1
    def pct(p: float) -> float:
        return lat[min(n - 1, int(n * p))] if n else 0.0

    print("=" * 56)
    print(f"Duration (wall)      : {wall:8.1f} s")
    print(f"Requests             : {n:8d}")
    print(f"Throughput           : {n / wall:8.1f} req/s")
    print(f"Errors               : {RESULTS['errors']:8d}  ({100 * RESULTS['errors'] / max(1, n):.2f}%)")
    if RESULTS["error_kinds"]:
        for k, v in sorted(RESULTS["error_kinds"].items(), key=lambda kv: -kv[1]):
            print(f"   {k:<24} {v}")
    print(f"Status codes         : {json.dumps(RESULTS['status_codes'])}")
    if n:
        print(f"Latency p50          : {pct(0.50):8.1f} ms")
        print(f"Latency p90          : {pct(0.90):8.1f} ms")
        print(f"Latency p99          : {pct(0.99):8.1f} ms")
        print(f"Latency max          : {lat[-1]:8.1f} ms")
        print(f"Latency mean         : {statistics.mean(lat):8.1f} ms")
    if args.write:
        print(f"Writes created       : {WRITES['created']:8d} (failed: {WRITES['failed']})")

    # pass/fail gates
    ok = True
    if n == 0:
        print("FAIL: no requests completed")
        return 1
    err_rate = RESULTS["errors"] / n
    if err_rate > 0.01:
        print(f"FAIL: error rate {100 * err_rate:.2f}% > 1%")
        ok = False
    if pct(0.99) > 5000:
        print(f"FAIL: p99 {pct(0.99):.0f} ms > 5000 ms")
        ok = False
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

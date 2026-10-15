"""
DCTA eval runner.

Reads the eval set xlsx and drives the deployed backend end to end:

  flow=no marker  -> POST /api/intent {rawTranscript, mode}
  flow=intent     -> POST /api/intent   (captures turnId for the chain)
  flow=resolve    -> POST /api/resolve  {turnId, resolutions}
  flow=confirm    -> POST /api/confirm  {turnId, envelope} (toy-signed)

Calls within the same session_id share a turnId so the clarify -> resolve ->
confirm handoff works exactly as the frontend does. Verdicts are PASS / FAIL /
SKIP, decided by matching response.type against expected_type (supports "a|b").

Usage:
    backend\\venv\\Scripts\\python.exe Eval\\run_eval.py [--url http://localhost:8080]
    ... --only 9          # run one session
    ... --expect draft|frozen
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests
from openpyxl import load_workbook

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "backend"))

XLSX = BASE / "Eval" / "DCTA Eval Set 1002.xlsx"

# Order matters and mirrors services/parser.py + services/crypto.py; importing
# the real helpers keeps the envelope byte-identical to the frontend contract.
from backend_imports import (
    build_confirm_envelope,
    compute_confirm_payload,
    toy_sign_available,
)

PAYEE_JOHN_TAN = {"id": "payee_john_tan", "name": "John Tan", "bank": "DBS", "account": "***9921"}


def load_cases(path: Path):
    ws = load_workbook(path, data_only=True)["Eval Set"]
    cases = []
    for r in range(3, ws.max_row + 1):
        row = [ws.cell(r, c).value for c in range(1, 9)]
        if not row[0] and not row[2]:
            continue
        cases.append({
            "session": row[0],
            "request": row[1],
            "query": row[2],
            "cvars": json.loads(row[3]) if row[3] else {},
            "expect": (row[5] or "").strip(),
            "req_id": row[6] or "",
        })
    return cases


def post(url: str, path: str, body: dict, timeout: int = 120):
    resp = requests.post(f"{url}/api{path}", json=body, timeout=timeout)
    data = resp.json() if resp.content else {}
    return resp.status_code, data


def verdict(expect: str, actual: str) -> bool:
    allowed = {e.strip() for e in expect.split("|") if e.strip()}
    return actual in allowed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8080")
    ap.add_argument("--only", type=int, default=None, help="run one session_id")
    ap.add_argument("--expect", default=None, help="act as if expected_type == X")
    ap.add_argument("--delay", type=float, default=0.0,
                    help="seconds to sleep between calls (ADP throttles bursts)")
    args = ap.parse_args()

    if not toy_sign_available():
        print("NOTE: KMS_KEY_ID or LOCAL_PUBLIC_KEY_PEM is configured; toy signing is off.")
        print("      'confirm' flow rows will be SKIP (signing happens on the device).\n")

    cases = [c for c in load_cases(XLSX) if args.only is None or c["session"] == args.only]

    turn_by_session: dict[int, str] = {}
    draft_by_session: dict[int, dict] = {}
    results = []
    passed = failed = skipped = 0

    for case in cases:
        flow = case["cvars"].get("flow", "intent")
        expect = args.expect or case["expect"]
        label = f"S{case['session']}.{case['request']} [{case['req_id']}]"
        query = (case["query"] or "").strip()

        try:
            if flow == "confirm":
                if not toy_sign_available():
                    skipped += 1
                    results.append((label, query, expect, "SKIP", "toy signing disabled on this deployment"))
                    continue
                turn = turn_by_session.get(case["session"])
                draft = draft_by_session.get(case["session"])
                if not turn or not draft:
                    results.append((label, query, expect, "FAIL", "missing turnId/draft from prior step"))
                    failed += 1
                    continue
                ts = int(time.time() * 1000)
                payload = compute_confirm_payload(turn, draft, ts)
                envelope = build_confirm_envelope(draft, ts, payload)
                code, data = post(args.url, "/confirm", {"turnId": turn, "envelope": envelope})
                actual = data.get("type", f"http{code}")
                detail = data.get("message", "")[:80]
            elif flow == "resolve":
                turn = turn_by_session.get(case["session"])
                if not turn:
                    results.append((label, query, expect, "FAIL", "no turnId captured from intent step"))
                    failed += 1
                    continue
                body = {
                    "turnId": turn,
                    "resolutions": [{
                        "field": "payee_disambiguation",
                        "intentIndex": 0,
                        "value": PAYEE_JOHN_TAN,
                    }],
                }
                code, data = post(args.url, "/resolve", body)
                actual = data.get("type", f"http{code}")
                detail = data.get("message", "")[:80]
                if actual == "draft":
                    draft_by_session[case["session"]] = data.get("draft")
            else:
                body = {
                    "rawTranscript": query,
                    "mode": case["cvars"].get("mode", "text"),
                }
                code, data = post(args.url, "/intent", body)
                actual = data.get("type", f"http{code}")
                detail = data.get("message", "")[:80]
                if flow == "intent" and data.get("turnId"):
                    turn_by_session[case["session"]] = data["turnId"]

            ok = verdict(expect, actual)
            passed += ok
            failed += not ok
            results.append((label, query, expect, actual, "" if ok else detail))
        except Exception as e:  # network / decode failures
            failed += 1
            results.append((label, query, expect, "ERROR", str(e)[:80]))
        if args.delay:
            time.sleep(args.delay)

    print(f"{'CASE':<22}{'EXPECT':<14}{'ACTUAL':<10}VERDICT  DETAIL")
    print("-" * 100)
    for label, query, expect, actual, detail in results:
        ok = actual in ("SKIP",) or verdict(expect, actual)
        state = "PASS" if ok else "FAIL"
        kind = "SKIP" if actual == "SKIP" else state
        short_q = query[:48].replace("\n", " ")
        print(f"{label:<22}{expect:<14}{actual:<10}{kind:<8} {short_q} {detail}")
    print("-" * 100)
    print(f"PASS {passed}  |  FAIL {failed}  |  SKIP {skipped}  |  total {len(results)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
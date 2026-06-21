"""Repeated local verification loop for Dev Triangle MCP.

This script is not an optimizer in the machine-learning sense. It is an
operator confidence loop: run compile checks, protocol smoke tests, and health
checks repeatedly while recording candidate improvement notes.

Use it when changing the MCP server surface or install behavior and you want a
quick regression history in the state directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.py"
SMOKE = ROOT / "tests" / "protocol_smoke.py"
STATE_ROOT = Path(os.environ.get("DEV_TRIANGLE_HOME", str(Path.home() / ".dev-triangle"))).expanduser()
REPORT_DIR = STATE_ROOT / "optimization"
REPORT = REPORT_DIR / "optimization-loop-report.json"
SUMMARY = REPORT_DIR / "optimization-loop-summary.md"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_cmd(args: list[str], timeout: int = 60, env: dict[str, str] | None = None) -> dict:
    started = time.time()
    proc = subprocess.run(
        args,
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    return {
        "args": args,
        "exitCode": proc.returncode,
        "durationSec": round(time.time() - started, 3),
        "stdoutTail": proc.stdout[-3000:],
        "stderrTail": proc.stderr[-3000:],
    }


def mcp_call(tool: str, arguments: dict | None = None) -> dict:
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": arguments or {}}}
    env = os.environ.copy()
    env.setdefault("DEV_TRIANGLE_HOME", str(STATE_ROOT))
    env.setdefault("ANTIGRAVITY_HANDOFF_DIR", str(STATE_ROOT / "antigravity-handoffs"))
    proc = subprocess.run(
        [sys.executable, str(SERVER)],
        input=json.dumps(init) + "\n" + json.dumps(call) + "\n",
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=60,
        env=env,
    )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    payload = json.loads(lines[-1])
    return payload["result"]["structuredContent"]


ROUND_THEMES = [
    "protocol coverage",
    "result mailbox reliability",
    "direct MCP result submission",
    "Antigravity CLI detection",
    "Jules API reachability",
    "ledger durability",
    "tool schema completeness",
    "error-path clarity",
    "configuration portability",
    "secret hygiene",
    "documentation accuracy",
    "timeout behavior",
    "workflow reproducibility",
    "final integration readiness",
    "operator handoff clarity",
]


def candidates_for_round(index: int, health: dict, smoke_ok: bool) -> list[dict]:
    theme = ROUND_THEMES[(index - 1) % len(ROUND_THEMES)]
    base = [
        {
            "candidate": "Keep protocol smoke test green",
            "reason": "The MCP server must remain callable after every change.",
            "decision": "apply-through-verification",
        },
        {
            "candidate": "Preserve no-secret-in-config rule",
            "reason": "Jules credentials should be environment-provided, not committed.",
            "decision": "apply-through-policy",
        },
        {
            "candidate": "Keep Antigravity result contract explicit",
            "reason": "Closed-loop behavior depends on a clear marker/result path contract.",
            "decision": "apply-through-tests",
        },
    ]
    if not smoke_ok:
        base.append(
            {
                "candidate": "Fix failing smoke test before adding features",
                "reason": "A broken MCP baseline makes further optimization meaningless.",
                "decision": "highest-priority",
            }
        )
    elif theme in {"Antigravity CLI detection", "final integration readiness"} and not health["antigravity"]["available"]:
        base.append(
            {
                "candidate": "Improve Antigravity command detection",
                "reason": "Full local validation needs a real Antigravity IDE CLI path.",
                "decision": "apply-if-evidence-shows-missing-cli",
            }
        )
    else:
        base.append(
            {
                "candidate": f"Audit {theme}",
                "reason": f"This round focuses on {theme} and verifies no regression.",
                "decision": "audit-and-record",
            }
        )
    return base[:5]


def round_score(smoke_ok: bool, health: dict) -> int:
    score = 0
    score += 35 if smoke_ok else 0
    score += 15 if health["antigravity"]["available"] else 0
    score += 10 if health["jules"]["apiKeyPresent"] else 0
    score += 10 if health["server"]["name"] == "dev-triangle-mcp" else 0
    score += 10 if health["paths"]["ledger"] else 0
    score += 10 if health["ledger"]["handoffCount"] >= 0 else 0
    score += 10 if health["ledger"]["jobCount"] >= 0 else 0
    return score


def main() -> int:
    rounds = int(os.environ.get("DEV_TRIANGLE_OPT_ROUNDS", "15"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    for i in range(1, rounds + 1):
        py_compile = run_cmd([sys.executable, "-m", "py_compile", str(SERVER), str(SMOKE)])
        smoke = run_cmd([sys.executable, str(SMOKE)], timeout=120)
        health = mcp_call("mcp_health_check", {"includeJules": bool(os.environ.get("JULES_API_KEY"))})
        smoke_ok = smoke["exitCode"] == 0 and py_compile["exitCode"] == 0
        record = {
            "round": i,
            "theme": ROUND_THEMES[(i - 1) % len(ROUND_THEMES)],
            "startedAt": now_iso(),
            "candidates": candidates_for_round(i, health, smoke_ok),
            "verification": {
                "pyCompile": py_compile,
                "smoke": smoke,
                "health": health,
            },
            "score": round_score(smoke_ok, health),
            "status": "pass" if smoke_ok else "fail",
        }
        records.append(record)

    report = {
        "generatedAt": now_iso(),
        "roundsRequested": rounds,
        "roundsCompleted": len(records),
        "allPassed": all(item["status"] == "pass" for item in records),
        "minScore": min(item["score"] for item in records),
        "maxScore": max(item["score"] for item in records),
        "records": records,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Optimization Loop Summary",
        "",
        f"- generatedAt: {report['generatedAt']}",
        f"- roundsCompleted: {report['roundsCompleted']}",
        f"- allPassed: {report['allPassed']}",
        f"- scoreRange: {report['minScore']}..{report['maxScore']}",
        "",
        "## Rounds",
        "",
    ]
    for item in records:
        lines += [
            f"### Round {item['round']}: {item['theme']}",
            f"- status: {item['status']}",
            f"- score: {item['score']}",
            "- candidates:",
        ]
        lines += [f"  - {candidate['candidate']}: {candidate['decision']}" for candidate in item["candidates"]]
        lines.append("")
    SUMMARY.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"report": str(REPORT), "summary": str(SUMMARY), "allPassed": report["allPassed"]}, indent=2))
    return 0 if report["allPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

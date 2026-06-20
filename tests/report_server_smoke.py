from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "antigravity_report_server.py"
TEST_STATE = ROOT / ".dev-triangle-report-test"


def rpc(proc: subprocess.Popen[str], request: dict) -> dict:
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("server exited without a response")
    return json.loads(line)


def main() -> int:
    TEST_STATE.mkdir(parents=True, exist_ok=True)
    handoff_dir = TEST_STATE / "antigravity-handoffs"
    result_dir = TEST_STATE / "antigravity-results"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = handoff_dir / "report-smoke.md"
    handoff_path.write_text("# Report smoke handoff\n", encoding="utf-8")
    ledger = {
        "schemaVersion": 1,
        "jobs": [],
        "handoffs": [
            {
                "id": "report-smoke",
                "provider": "antigravity",
                "title": "Report Server Smoke",
                "status": "READY",
                "path": str(handoff_path),
                "repoPath": str(ROOT),
            }
        ],
    }
    (TEST_STATE / "jobs.json").write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

    env = os.environ.copy()
    env["DEV_TRIANGLE_HOME"] = str(TEST_STATE)
    env["ANTIGRAVITY_HANDOFF_DIR"] = str(handoff_dir)
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    try:
        init = rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert init["result"]["serverInfo"]["name"] == "dev-triangle-report"

        tools = rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {tool["name"] for tool in tools["result"]["tools"]}
        assert names == {"dev_triangle_report_health", "complete_dev_triangle_handoff"}

        health = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "dev_triangle_report_health", "arguments": {}},
            },
        )
        assert health["result"]["isError"] is False

        complete = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "complete_dev_triangle_handoff",
                    "arguments": {
                        "handoff": "report-smoke",
                        "status": "COMPLETED",
                        "recommendation": "PASS",
                        "summary": "Report server smoke passed.",
                        "commandsRun": ["python tests/report_server_smoke.py"],
                        "findings": ["Result marker was written."],
                    },
                },
            },
        )
        assert complete["result"]["isError"] is False
        result = complete["result"]["structuredContent"]["result"]
        assert result["ready"] is True
        assert "DEV_TRIANGLE_RESULT_READY" in result["content"]

        updated = json.loads((TEST_STATE / "jobs.json").read_text(encoding="utf-8"))
        assert updated["handoffs"][0]["status"] == "COMPLETED"
        print("Report server smoke test passed.")
        print(f"Tool count: {len(names)}")
        return 0
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())

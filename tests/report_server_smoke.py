# Dev Triangle MCP source maintenance contract
# 上下游: 由 CI 與 .dev-triangle/verify.json 的 default suite 直接以 python 執行；把 antigravity_report_server.py 當成真的 stdio 子行程啟動；狀態寫在 repo 底下的 .dev-triangle-report-test，不碰使用者的帳本
# 檔案路徑: dev-triangle-mcp/tests/report_server_smoke.py
# 產生時間: 2026-08-19 17:30 +08:00
# 版本: v1.1
# 功能說明: 檢查給 worker 用的那台小伺服器只露出該露的兩支工具，而且送進來的結果會被正確標成「代理人自述」寫進共用帳本
# 模組定位: 端對端煙霧測試，同時是 INV-02(工具面要窄)與 INV-03(自述要標記)的守門人。它「是」對回報介面的檢查；它「不是」對主伺服器的檢查(那是 protocol_smoke.py)
# 主要責任:
#   1. 斷言工具集合剛好是 dev_triangle_report_health 與 complete_dev_triangle_handoff 兩支
#   2. 送一筆完成回報，確認 result markdown 帶結束標記
#   3. 斷言帳本裡的 submittedResult 標了 evidenceLevel: agent_asserted 並帶 evidenceRef 欄位
# 維護提醒:
#   - 第 1 條的斷言用的是集合相等而不是包含，這是刻意的。多出任何一支工具都必須讓這裡變紅
#   - 不得移除 evidenceLevel 斷言。少了它，回報伺服器停止標記時沒有任何東西會紅(2026-08-19 突變測試實際踩到過)
# 驗證方式:
#   - python tests/report_server_smoke.py
# ------------------------------------------------------------

"""Smoke test for the report-only MCP server.

This verifies the narrow worker-facing surface:

- Only health and completion tools are exposed.
- A known handoff can be marked completed.
- The result markdown includes DEV_TRIANGLE_RESULT_READY.
- The shared ledger is updated.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "antigravity_report_server.py"
# Use a per-process state folder so this smoke test can run beside other local
# checks without fighting over jobs.json.
TEST_STATE = Path(
    os.environ.get("DEV_TRIANGLE_REPORT_TEST_HOME", str(ROOT / ".dev-triangle-report-test" / str(os.getpid())))
)


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
    # Build a small ledger fixture by hand so this test stays independent from
    # the main MCP server and proves the report server can stand alone.
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
        # INV-03: whatever a worker submits here is an assertion, and the ledger
        # has to say so. Without this label the audit trail cannot tell a claim
        # apart from a measurement after the fact.
        submitted = updated["handoffs"][0]["submittedResult"]
        assert submitted["evidenceLevel"] == "agent_asserted"
        assert "evidenceRef" in submitted
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

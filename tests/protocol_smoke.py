"""Smoke test for the main Dev Triangle MCP server.

The test runs the server as a real stdio MCP process and exercises the important
control-plane paths:

- JSON-RPC initialization and tool listing.
- Jules-independent ledger operations.
- Local-project-to-Jules repo preparation dry-run safety.
- Antigravity handoff creation.
- CLI detection and dry-run behavior.
- Closed-loop result capture using a fake Antigravity executable.

The fake executable is used only for deterministic protocol testing. Real local
validation is covered by scripts/demo-user-flow.ps1 on machines with agy.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.py"
# Keep each smoke run isolated. Local developers may run scripts/smoke.ps1 while
# also invoking this test directly, and shared ledgers make those runs flaky.
TEST_STATE = Path(os.environ.get("DEV_TRIANGLE_TEST_HOME", str(ROOT / ".dev-triangle-test" / str(os.getpid()))))


def rpc(proc: subprocess.Popen[str], request: dict) -> dict:
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("server exited without a response")
    return json.loads(line)


def create_fake_antigravity() -> Path:
    # NOTE: This fake executable proves the mailbox contract without depending
    # on external auth, network, or the real Antigravity model runtime.
    TEST_STATE.mkdir(parents=True, exist_ok=True)
    fake_py = TEST_STATE / "fake_antigravity.py"
    fake_py.write_text(
        r'''
from __future__ import annotations

import re
import sys
from pathlib import Path


prompt = " ".join(sys.argv[1:])
match = re.search(r"RESULT_PATH:\s*(.+?)(?:;|\r?\n|$)", prompt)
if not match:
    print("RESULT_PATH missing", file=sys.stderr)
    raise SystemExit(2)
path = Path(match.group(1).strip())
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(
    "status: pass\n"
    "recommendation: merge\n"
    "commands run: fake smoke test\n"
    "findings: fake closed-loop verification completed\n"
    "DEV_TRIANGLE_RESULT_READY\n",
    encoding="utf-8",
)
print(f"wrote {path}")
'''.lstrip(),
        encoding="utf-8",
    )
    if os.name == "nt":
        fake_cmd = TEST_STATE / "fake-antigravity.cmd"
        fake_cmd.write_text(f'@echo off\n"{sys.executable}" "{fake_py}" %*\n', encoding="utf-8")
        return fake_cmd
    fake_sh = TEST_STATE / "fake-antigravity"
    fake_sh.write_text(f'#!/usr/bin/env sh\n"{sys.executable}" "{fake_py}" "$@"\n', encoding="utf-8")
    fake_sh.chmod(fake_sh.stat().st_mode | stat.S_IEXEC)
    return fake_sh


def main() -> int:
    env = os.environ.copy()
    env["DEV_TRIANGLE_HOME"] = str(TEST_STATE)
    env["ANTIGRAVITY_HANDOFF_DIR"] = str(TEST_STATE / "antigravity-handoffs")
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
        init = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke"}},
            },
        )
        assert init["result"]["serverInfo"]["name"] == "dev-triangle-mcp"

        tools = rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {tool["name"] for tool in tools["result"]["tools"]}
        assert "jules_create_session" in names
        assert "prepare_jules_repo" in names
        assert "create_antigravity_handoff" in names
        assert "antigravity_detect_cli" in names
        assert "run_antigravity_handoff" in names
        assert "antigravity_get_result" in names
        assert "submit_antigravity_result" in names
        assert "mcp_health_check" in names
        assert "job_list" in names

        jobs = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "job_list", "arguments": {"limit": 5}},
            },
        )
        assert jobs["result"]["isError"] is False

        jules_project = Path(tempfile.mkdtemp(prefix="dev-triangle-jules-prep-")) / "jules-local-project"
        jules_project.mkdir(parents=True, exist_ok=True)
        (jules_project / "app.py").write_text("print('hello from jules prep smoke')\n", encoding="utf-8")
        (jules_project / ".env").write_text("JULES_API_KEY=AQ.fakeSmokeSecretValue123456789\n", encoding="utf-8")

        prep_dry_run = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "prepare_jules_repo",
                    "arguments": {"repoPath": str(jules_project)},
                },
            },
        )
        assert prep_dry_run["result"]["isError"] is False
        prep = prep_dry_run["result"]["structuredContent"]
        assert prep["status"] == "DRY_RUN"
        assert prep["publish"] is False
        assert prep["safety"]["blockingFindings"]
        assert not (jules_project / ".gitignore").exists()

        prep_guard = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "prepare_jules_repo",
                    "arguments": {"repoPath": str(jules_project), "publish": True},
                },
            },
        )
        assert prep_guard["result"]["isError"] is True
        assert "confirmPublish=true" in prep_guard["result"]["structuredContent"]["error"]

        handoff = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "create_antigravity_handoff",
                    "arguments": {
                        "title": "Smoke Handoff",
                        "objective": "Verify MCP handoff plumbing.",
                        "repoPath": str(ROOT),
                    },
                },
            },
        )
        assert handoff["result"]["isError"] is False
        handoff_id = handoff["result"]["structuredContent"]["handoff"]["id"]

        detect = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "antigravity_detect_cli",
                    "arguments": {"command": "definitely-not-antigravity-cli-test"},
                },
            },
        )
        assert detect["result"]["isError"] is False
        assert detect["result"]["structuredContent"]["available"] is False

        dry_run = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "run_antigravity_handoff",
                    "arguments": {
                        "handoff": handoff_id,
                        "command": "definitely-not-antigravity-cli-test",
                        "dryRun": True,
                    },
                },
            },
        )
        assert dry_run["result"]["isError"] is False
        assert dry_run["result"]["structuredContent"]["dryRun"] is True

        missing_cli = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "run_antigravity_handoff",
                    "arguments": {
                        "handoff": handoff_id,
                        "command": "definitely-not-antigravity-cli-test",
                    },
                },
            },
        )
        assert missing_cli["result"]["isError"] is True
        assert "Antigravity CLI command was not found" in missing_cli["result"]["structuredContent"]["error"]

        fake_cmd = create_fake_antigravity()
        closed_loop = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "run_antigravity_handoff",
                    "arguments": {
                        "handoff": handoff_id,
                        "command": str(fake_cmd),
                        "executionStyle": "prompt_arg",
                        "waitForResult": True,
                        "resultTimeoutSec": 10,
                        "pollIntervalSec": 1,
                    },
                },
            },
        )
        assert closed_loop["result"]["isError"] is False
        assert closed_loop["result"]["structuredContent"]["status"] == "COMPLETED"
        assert closed_loop["result"]["structuredContent"]["result"]["ready"] is True
        assert "recommendation: merge" in closed_loop["result"]["structuredContent"]["result"]["content"]

        get_result = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {
                    "name": "antigravity_get_result",
                    "arguments": {"handoff": handoff_id},
                },
            },
        )
        assert get_result["result"]["isError"] is False
        assert get_result["result"]["structuredContent"]["status"] == "COMPLETED"
        assert get_result["result"]["structuredContent"]["result"]["ready"] is True

        direct_submit = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {
                    "name": "submit_antigravity_result",
                    "arguments": {
                        "handoff": handoff_id,
                        "status": "COMPLETED",
                        "recommendation": "merge",
                        "summary": "Direct MCP result submission path works.",
                        "commandsRun": ["fake direct submission"],
                        "findings": ["submit_antigravity_result stored the result"],
                    },
                },
            },
        )
        assert direct_submit["result"]["isError"] is False
        assert direct_submit["result"]["structuredContent"]["result"]["ready"] is True

        health = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": {"name": "mcp_health_check", "arguments": {}},
            },
        )
        assert health["result"]["isError"] is False
        assert health["result"]["structuredContent"]["server"]["name"] == "dev-triangle-mcp"

        print("MCP smoke test passed.")
        print(f"Tool count: {len(names)}")
        print(f"Ledger path: {jobs['result']['structuredContent']['ledgerPath']}")
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

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
import sqlite3
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


def create_empty_antigravity() -> Path:
    TEST_STATE.mkdir(parents=True, exist_ok=True)
    fake_py = TEST_STATE / "empty_antigravity.py"
    fake_py.write_text(
        "from __future__ import annotations\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        fake_cmd = TEST_STATE / "empty-antigravity.cmd"
        fake_cmd.write_text(f'@echo off\n"{sys.executable}" "{fake_py}" %*\n', encoding="utf-8")
        return fake_cmd
    fake_sh = TEST_STATE / "empty-antigravity"
    fake_sh.write_text(f'#!/usr/bin/env sh\n"{sys.executable}" "{fake_py}" "$@"\n', encoding="utf-8")
    fake_sh.chmod(fake_sh.stat().st_mode | stat.S_IEXEC)
    return fake_sh


def create_fake_agy_transcript() -> Path:
    TEST_STATE.mkdir(parents=True, exist_ok=True)
    fake_py = TEST_STATE / "fake_agy_transcript.py"
    fake_py.write_text(
        r'''
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


args = sys.argv[1:]
log_path = None
for index, arg in enumerate(args):
    if arg == "--log-file" and index + 1 < len(args):
        log_path = Path(args[index + 1])
        break

conversation_id = "11111111-2222-3333-4444-555555555555"
if log_path is not None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(f"conversation {conversation_id}\n", encoding="utf-8")

home = Path(os.environ["ANTIGRAVITY_CLI_HOME"])
transcript = home / "brain" / conversation_id / ".system_generated" / "logs" / "transcript.jsonl"
transcript.parent.mkdir(parents=True, exist_ok=True)
content = (
    "status: pass\n"
    "recommendation: merge\n"
    "commands run: fake agy transcript smoke\n"
    "findings: transcript fallback recovered the result\n"
    "DEV_TRIANGLE_RESULT_READY\n"
)
transcript.write_text(
    json.dumps(
        {
            "step_index": 0,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "content": content,
        }
    )
    + "\n",
    encoding="utf-8",
)
raise SystemExit(0)
'''.lstrip(),
        encoding="utf-8",
    )
    if os.name == "nt":
        fake_cmd = TEST_STATE / "agy.cmd"
        fake_cmd.write_text(f'@echo off\n"{sys.executable}" "{fake_py}" %*\n', encoding="utf-8")
        return fake_cmd
    fake_sh = TEST_STATE / "agy"
    fake_sh.write_text(f'#!/usr/bin/env sh\n"{sys.executable}" "{fake_py}" "$@"\n', encoding="utf-8")
    fake_sh.chmod(fake_sh.stat().st_mode | stat.S_IEXEC)
    return fake_sh


def create_empty_antigravity_with_conversation_result() -> Path:
    TEST_STATE.mkdir(parents=True, exist_ok=True)
    fake_py = TEST_STATE / "empty_antigravity_with_conversation_result.py"
    fake_py.write_text(
        r'''
from __future__ import annotations

import os
import re
import sqlite3
import sys
import uuid
from pathlib import Path


prompt = " ".join(sys.argv[1:])
conversation_dir = Path(os.environ["ANTIGRAVITY_AGY_CONVERSATION_DIR"])
conversation_dir.mkdir(parents=True, exist_ok=True)
db_path = conversation_dir / f"{uuid.uuid4()}.db"
marker = "DEV_TRIANGLE_RESULT_READY"
result_text = (
    "status: pass\n"
    "recommendation: merge\n"
    "commands run: fake agy sqlite fallback\n"
    "findings: stdout bridge was empty but Antigravity conversation DB had the final report\n"
    f"{marker}\n"
)
with sqlite3.connect(db_path) as con:
    con.execute(
        "create table steps (idx integer, step_type integer, status integer, has_subtrajectory integer, "
        "metadata blob, error_details blob, permissions blob, task_details blob, render_info blob, "
        "step_payload blob, step_format integer)"
    )
    con.execute(
        "insert into steps values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (0, 14, 3, 0, b"", None, None, None, None, prompt.encode("utf-8"), 0),
    )
    con.execute(
        "insert into steps values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, 15, 3, 0, b"", None, None, None, None, f"bot-result:\n{result_text}".encode("utf-8"), 0),
    )
raise SystemExit(0)
'''.lstrip(),
        encoding="utf-8",
    )
    if os.name == "nt":
        fake_cmd = TEST_STATE / "empty-agy-with-conversation-result.cmd"
        fake_cmd.write_text(f'@echo off\n"{sys.executable}" "{fake_py}" %*\n', encoding="utf-8")
        return fake_cmd
    fake_sh = TEST_STATE / "empty-agy-with-conversation-result"
    fake_sh.write_text(f'#!/usr/bin/env sh\n"{sys.executable}" "{fake_py}" "$@"\n', encoding="utf-8")
    fake_sh.chmod(fake_sh.stat().st_mode | stat.S_IEXEC)
    return fake_sh


def main() -> int:
    env = os.environ.copy()
    env["DEV_TRIANGLE_HOME"] = str(TEST_STATE)
    env["ANTIGRAVITY_HANDOFF_DIR"] = str(TEST_STATE / "antigravity-handoffs")
    env["ANTIGRAVITY_CLI_HOME"] = str(TEST_STATE / "antigravity-cli-home")
    env["ANTIGRAVITY_AGY_CONVERSATION_DIR"] = str(TEST_STATE / "antigravity-conversations")
    env["ANTIGRAVITY_AGY_MODEL"] = "Gemini 3.5 Flash (Medium)"
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

        agy_dry_run = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 81,
                "method": "tools/call",
                "params": {
                    "name": "run_antigravity_handoff",
                    "arguments": {
                        "handoff": handoff_id,
                        "command": "agy.exe",
                        "executionStyle": "agy_print",
                        "dryRun": True,
                    },
                },
            },
        )
        assert agy_dry_run["result"]["isError"] is False
        agy_command = agy_dry_run["result"]["structuredContent"]["commandLine"]
        assert "--model" not in agy_command
        assert "--add-dir" in agy_command
        assert "--log-file" in agy_command
        print_idx = agy_command.index("--print")
        assert agy_command[print_idx + 1].startswith("Use the handoff at ")
        assert agy_command[print_idx + 2] == "--print-timeout"

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

        fake_agy = create_fake_agy_transcript()
        agy_transcript = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 103,
                "method": "tools/call",
                "params": {
                    "name": "run_antigravity_handoff",
                    "arguments": {
                        "handoff": handoff_id,
                        "command": str(fake_agy),
                        "executionStyle": "agy_print",
                        "waitForResult": True,
                        "resultTimeoutSec": 10,
                        "emptyStdoutResultGraceSec": 1,
                        "pollIntervalSec": 1,
                    },
                },
            },
        )
        assert agy_transcript["result"]["isError"] is False
        agy_payload = agy_transcript["result"]["structuredContent"]
        assert agy_payload["status"] == "COMPLETED"
        assert agy_payload["stdoutEmpty"] is True
        assert agy_payload["result"]["ready"] is True
        assert agy_payload["result"]["source"] == "antigravity_transcript"
        assert "transcript fallback recovered" in agy_payload["result"]["content"]

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

        empty_cmd = create_empty_antigravity()
        empty_closed_loop = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 101,
                "method": "tools/call",
                "params": {
                    "name": "run_antigravity_handoff",
                    "arguments": {
                        "handoff": handoff_id,
                        "command": str(empty_cmd),
                        "executionStyle": "agy_print",
                        "waitForResult": True,
                        "resultTimeoutSec": 10,
                        "emptyStdoutResultGraceSec": 1,
                        "pollIntervalSec": 1,
                    },
                },
            },
        )
        assert empty_closed_loop["result"]["isError"] is False
        assert empty_closed_loop["result"]["structuredContent"]["status"] == "DEGRADED_NO_RESULT"
        assert empty_closed_loop["result"]["structuredContent"]["stdoutEmpty"] is True

        empty_db_cmd = create_empty_antigravity_with_conversation_result()
        db_fallback_closed_loop = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 102,
                "method": "tools/call",
                "params": {
                    "name": "run_antigravity_handoff",
                    "arguments": {
                        "handoff": handoff_id,
                        "command": str(empty_db_cmd),
                        "executionStyle": "agy_print",
                        "waitForResult": True,
                        "resultTimeoutSec": 10,
                        "emptyStdoutResultGraceSec": 1,
                        "pollIntervalSec": 1,
                    },
                },
            },
        )
        assert db_fallback_closed_loop["result"]["isError"] is False
        db_fallback = db_fallback_closed_loop["result"]["structuredContent"]
        assert db_fallback["status"] == "COMPLETED"
        assert db_fallback["stdoutEmpty"] is True
        assert db_fallback["result"]["ready"] is True
        assert db_fallback["result"]["source"] == "antigravity_conversation_db"
        assert "fake agy sqlite fallback" in db_fallback["result"]["content"]

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

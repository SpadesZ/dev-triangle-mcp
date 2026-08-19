# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 收集執行；import server 並在 tmp_path 建臨時 repo 與 .dev-triangle/verify.json；會啟動真的子行程，但只跑本檔自己寫出來的指令稿
# 檔案路徑: dev-triangle-mcp/tests/test_verification_suite.py
# 產生時間: 2026-08-19 13:15 +08:00
# 版本: v1.0
# 功能說明: 釘住受限驗證執行器的四條硬規則——呼叫端不得傳指令、沒宣告就不猜、沒確認過就不跑、非 0 要被收集而不是被丟成例外
# 模組定位: W03 的突變驗證載體，也是 S4.1 machine_verified_rate 的分子來源測試。它「是」對執行器行為的測試；它「不是」對 Quality Gate 裁決的測試（那是 tests/test_quality_gate.py）
# 主要責任:
#   1. test_rejects_caller_supplied_command —— 守 INV-01
#   2. test_unconfirmed_suite_hash_blocks / test_new_commit_requires_reconfirmation —— 守 F4、NOTE-007
#   3. test_nonzero_exit_is_captured_not_raised —— 守本包最容易寫錯的一行（allow_failure）
#   4. test_timeout_kills_the_whole_process_tree —— 守 NOTE-006
# 維護提醒:
#   - 不得為了讓測試跑快而把確認閘門的斷言拿掉。那道閘是 gate #1 核准的三個條件之一
#   - 子行程測試若在 CI 上不穩，正確做法是加長 timeout 或跳過該平台，不得改成只斷言父行程已死
# 驗證方式:
#   - python -m pytest -q tests\test_verification_suite.py
# ------------------------------------------------------------

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import server


def write_manifest(repo: Path, suites: dict) -> Path:
    manifest = repo / ".dev-triangle" / "verify.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"schemaVersion": 1, "suites": suites}, indent=2), encoding="utf-8")
    return manifest


def make_repo(tmp_path: Path, name: str = "fixture-repo") -> Path:
    repo = tmp_path / name
    repo.mkdir(parents=True, exist_ok=True)
    return repo


def run(**kwargs):
    return server.tool_run_verification_suite(kwargs)


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in (result.stdout or "")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# ---------------------------------------------------------------------------
# INV-01: callers cannot supply commands
# ---------------------------------------------------------------------------


def test_rejects_caller_supplied_command(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write_manifest(repo, {"default": {"commands": [[sys.executable, "-c", "pass"]], "timeoutSec": 60}})

    with pytest.raises(server.ToolError) as excinfo:
        run(repoPath=str(repo), suiteName="default", confirmSuite=True, command="echo pwned")
    assert "never accepts commands" in str(excinfo.value)


def test_tool_schema_has_no_command_parameter() -> None:
    tool = [item for item in server.TOOLS if item["name"] == "run_verification_suite"][0]
    properties = tool["inputSchema"]["properties"]
    assert "command" not in properties
    assert "commands" not in properties
    assert tool["inputSchema"]["additionalProperties"] is False


# ---------------------------------------------------------------------------
# A3 rule 1: no manifest means no guessing
# ---------------------------------------------------------------------------


def test_no_suite_when_manifest_missing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    result = run(repoPath=str(repo), confirmSuite=True)
    assert result["status"] == "NO_SUITE"


def test_no_suite_when_name_not_declared(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write_manifest(repo, {"quick": {"commands": [[sys.executable, "-c", "pass"]], "timeoutSec": 60}})
    result = run(repoPath=str(repo), suiteName="default", confirmSuite=True)
    assert result["status"] == "NO_SUITE"
    assert result["availableSuites"] == ["quick"]


# ---------------------------------------------------------------------------
# F4 + NOTE-007: the confirmation gate
# ---------------------------------------------------------------------------


def test_unconfirmed_suite_hash_blocks(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    marker = repo / "it-ran.txt"
    write_manifest(
        repo,
        {
            "default": {
                "commands": [[sys.executable, "-c", f"open(r'{marker}', 'w').write('ran')"]],
                "timeoutSec": 60,
            }
        },
    )

    result = run(repoPath=str(repo), suiteName="default")
    assert result["status"] == "NEEDS_CONFIRMATION"
    assert result["commands"], "the caller must be shown what it is about to approve"
    assert not marker.exists(), "nothing may run before confirmation"

    confirmed = run(repoPath=str(repo), suiteName="default", confirmSuite=True)
    assert confirmed["status"] == "PASSED"
    assert marker.exists()

    # Confirmed once, remembered afterwards.
    again = run(repoPath=str(repo), suiteName="default")
    assert again["status"] == "PASSED"


def test_edited_manifest_needs_reconfirmation(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write_manifest(repo, {"default": {"commands": [[sys.executable, "-c", "pass"]], "timeoutSec": 60}})
    assert run(repoPath=str(repo), confirmSuite=True)["status"] == "PASSED"

    write_manifest(repo, {"default": {"commands": [[sys.executable, "-c", "print(1)"]], "timeoutSec": 60}})
    assert run(repoPath=str(repo))["status"] == "NEEDS_CONFIRMATION"


def test_new_commit_requires_reconfirmation(tmp_path: Path) -> None:
    # NOTE(NOTE-007): confirming the manifest alone would leave the scripts it
    # points at free to change underneath the approval.
    repo = make_repo(tmp_path, "git-repo")
    git = ["git", "-C", str(repo)]
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    subprocess.run([*git, "config", "user.email", "test@example.invalid"], check=True, capture_output=True)
    subprocess.run([*git, "config", "user.name", "test"], check=True, capture_output=True)
    write_manifest(repo, {"default": {"commands": [[sys.executable, "-c", "pass"]], "timeoutSec": 60}})
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
    subprocess.run([*git, "commit", "-qm", "first"], check=True, capture_output=True)

    first = run(repoPath=str(repo), confirmSuite=True)
    assert first["status"] == "PASSED"
    assert first["verification"]["gitHeadSha"], "a git repo must contribute its HEAD to the fingerprint"

    # The manifest is untouched; only the code it points at moved.
    (repo / "code.py").write_text("x = 2\n", encoding="utf-8")
    subprocess.run([*git, "commit", "-qam", "second"], check=True, capture_output=True)

    assert run(repoPath=str(repo))["status"] == "NEEDS_CONFIRMATION"


# ---------------------------------------------------------------------------
# The evidence itself
# ---------------------------------------------------------------------------


def test_passing_suite_records_machine_evidence(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write_manifest(
        repo,
        {"default": {"commands": [[sys.executable, "-c", "print('hello from the suite')"]], "timeoutSec": 60}},
    )

    result = run(repoPath=str(repo), confirmSuite=True)
    verification = result["verification"]
    assert result["status"] == "PASSED"
    assert verification["evidenceLevel"] == server.EVIDENCE_MACHINE
    assert verification["exitCode"] == 0
    assert verification["isPrimarySuite"] is True

    log = Path(verification["stdoutPath"])
    assert log.exists()
    assert "hello from the suite" in log.read_text(encoding="utf-8")


def test_nonzero_exit_is_captured_not_raised(tmp_path: Path) -> None:
    # The single easiest line to get wrong in this package: without
    # allow_failure the non-zero exit becomes an exception and the evidence
    # this whole upgrade exists to collect is thrown away.
    repo = make_repo(tmp_path)
    write_manifest(
        repo,
        {"default": {"commands": [[sys.executable, "-c", "import sys; sys.exit(3)"]], "timeoutSec": 60}},
    )

    result = run(repoPath=str(repo), confirmSuite=True)
    assert result["status"] == "FAILED"
    assert result["verification"]["exitCode"] == 3
    assert result["verification"]["evidenceLevel"] == server.EVIDENCE_MACHINE


def test_first_failure_stops_the_suite(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    second_marker = repo / "second-ran.txt"
    write_manifest(
        repo,
        {
            "default": {
                "commands": [
                    [sys.executable, "-c", "import sys; sys.exit(1)"],
                    [sys.executable, "-c", f"open(r'{second_marker}', 'w').write('ran')"],
                ],
                "timeoutSec": 60,
            }
        },
    )

    result = run(repoPath=str(repo), confirmSuite=True)
    assert result["status"] == "FAILED"
    assert len(result["verification"]["executed"]) == 1
    assert not second_marker.exists()


def test_missing_executable_is_reported_without_inventing_an_exit_code(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write_manifest(repo, {"default": {"commands": ["definitely-not-a-real-binary-xyz"], "timeoutSec": 60}})

    result = run(repoPath=str(repo), confirmSuite=True)
    assert result["status"] == "FAILED"
    assert result["verification"]["exitCode"] is None
    assert result["verification"]["executed"][0]["status"] == "COMMAND_NOT_FOUND"


def test_string_commands_keep_windows_paths_intact() -> None:
    tokens = server.tokenize_suite_command(r'python C:\tools\run.py --flag "two words"')
    assert tokens == ["python", r"C:\tools\run.py", "--flag", "two words"]


# ---------------------------------------------------------------------------
# NOTE-006: the whole tree, not just the parent
# ---------------------------------------------------------------------------


def test_timeout_kills_the_whole_process_tree(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    pid_file = repo / "child.pid"
    script = repo / "spawn.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "Path(sys.argv[1]).write_text(str(child.pid))\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    write_manifest(
        repo,
        {"default": {"commands": [[sys.executable, str(script), str(pid_file)]], "timeoutSec": 3}},
    )

    result = run(repoPath=str(repo), confirmSuite=True)
    assert result["status"] == "FAILED"
    assert result["verification"]["executed"][0]["status"] == "TIMED_OUT"

    child_pid = int(pid_file.read_text(encoding="utf-8").strip())
    deadline = time.time() + 10
    while time.time() < deadline and pid_alive(child_pid):
        time.sleep(0.25)
    assert not pid_alive(child_pid), "the grandchild outlived the timeout; only the parent was killed"

# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 收集執行；import providers.cli_agent / dispatch / profiles 與 server；在 tmp_path 造一支假的 CLI 腳本當作 agent，實際啟動它，不呼叫任何真實 CLI 或網路
# 檔案路徑: dev-triangle-mcp/tests/test_cli_agent.py
# 產生時間: 2026-08-19 18:55 +08:00
# 版本: v1.0
# 功能說明: 釘住「用訂閱制 CLI 當某個角色」這條路上的四件事——指令列逐字照抄、token 量不到就說量不到、失敗不自動換人、以及可執行檔永遠不能用講的指定
# 模組定位: W14 的突變驗證載體，守 NOTE-009～NOTE-012。它「是」對 CLI 傳輸層與路由層的測試；它「不是」對受限驗證執行器的測試（那支的指令來自目標 repo，本檔的指令來自使用者 profile，兩者的信任模型相反）
# 主要責任:
#   1. test_args_are_passed_verbatim / test_model_is_a_label_not_a_flag —— 守 NOTE-009
#   2. test_cli_usage_is_empty_not_zero —— 守 NOTE-010
#   3. test_dispatch_does_not_fall_back —— 守 NOTE-011
#   4. test_command_is_never_nl_writable —— 守 NOTE-012，本檔最重要的一支
# 維護提醒:
#   - 第 4 支不得放寬。它擋的是「注入式設定變更」從『改端點』升級成『跑任意程式』，那是跨越 INV-01 的那條線
#   - 假 CLI 要用真的子行程跑，不得 monkeypatch 掉 run_native。指令列組得對不對正是被測的東西
# 驗證方式:
#   - python -m pytest -q tests\test_cli_agent.py
# ------------------------------------------------------------

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

import server
from providers import cli_agent, dispatch, profiles


def make_fake_cli(tmp_path: Path, body: str, name: str = "fake-agent") -> Path:
    """A real executable that echoes what it was given, so argv shape is testable."""
    script = tmp_path / f"{name}.py"
    script.write_text(body, encoding="utf-8")
    if os.name == "nt":
        launcher = tmp_path / f"{name}.cmd"
        launcher.write_text(f'@echo off\n"{sys.executable}" "{script}" %*\n', encoding="utf-8")
        return launcher
    launcher = tmp_path / name
    launcher.write_text(f'#!/usr/bin/env sh\n"{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    return launcher


# Reports both channels so tests can see exactly what the CLI received.
ECHO_BOTH = (
    "import json, sys\n"
    "print(json.dumps({'argv': sys.argv[1:], 'stdin': sys.stdin.read()}))\n"
)


def cli_binding(command: str, **kwargs: Any) -> profiles.RoleBinding:
    return profiles.RoleBinding(
        slot=kwargs.pop("slot", "architect"),
        kind="cli",
        command=command,
        enabled=True,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# NOTE-009: args verbatim, model is a label
# ---------------------------------------------------------------------------


def test_args_are_passed_verbatim(tmp_path: Path) -> None:
    fake = make_fake_cli(tmp_path, ECHO_BOTH)
    binding = cli_binding(str(fake), args=("--model", "some-model", "--yolo"), prompt_arg="-p")
    assert cli_agent.build_command(binding, "THE PROMPT")[1:] == [
        "--model",
        "some-model",
        "--yolo",
        "-p",
    ]


def test_model_is_a_label_not_a_flag(tmp_path: Path) -> None:
    # NOTE(NOTE-009): the model field must not become a flag this project invents.
    fake = make_fake_cli(tmp_path, ECHO_BOTH)
    line = cli_agent.build_command(cli_binding(str(fake), model="some-model", prompt_arg="-p"))
    assert "--model" not in line
    assert "some-model" not in line
    assert line[1:] == ["-p"]


def test_prompt_is_not_on_the_command_line_by_default(tmp_path: Path) -> None:
    # NOTE(NOTE-013): stdin is the default channel.
    fake = make_fake_cli(tmp_path, ECHO_BOTH)
    line = cli_agent.build_command(cli_binding(str(fake), prompt_arg="-p"), "THE PROMPT")
    assert "THE PROMPT" not in line


def test_prompt_via_arg_puts_it_on_the_command_line(tmp_path: Path) -> None:
    fake = make_fake_cli(tmp_path, ECHO_BOTH)
    binding = cli_binding(str(fake), prompt_arg="-p", prompt_via="arg")
    assert cli_agent.build_command(binding, "THE PROMPT")[1:] == ["-p", "THE PROMPT"]


def test_real_cli_receives_the_expected_argv(tmp_path: Path) -> None:
    fake = make_fake_cli(tmp_path, ECHO_BOTH)
    binding = cli_binding(str(fake), args=("--flag",), prompt_arg="-p")

    result = cli_agent.run_agent(binding, system="SYS", user="USER")

    received = json.loads(result["text"])
    assert received["argv"] == ["--flag", "-p"]
    assert received["stdin"].startswith("SYS")
    assert "USER" in received["stdin"]


def test_multiline_prompt_survives_via_stdin(tmp_path: Path) -> None:
    # NOTE(NOTE-013): passing this as an argv element loses everything after
    # the first newline when a Windows .cmd shim re-parses the command line -
    # which is what npm-installed agent CLIs are. It also exceeds the ~32KB
    # command-line ceiling on a realistic repo outline.
    fake = make_fake_cli(tmp_path, ECHO_BOTH)
    big_user = "\n".join(f"line {index}: some repo content" for index in range(2000))

    result = cli_agent.run_agent(cli_binding(str(fake)), system="SYS", user=big_user)

    received = json.loads(result["text"])
    assert len(big_user) > 32_000, "the fixture must actually exceed the command-line ceiling"
    assert received["argv"] == [], "nothing but flags belongs on the command line"
    assert "line 0: some repo content" in received["stdin"]
    assert "line 1999: some repo content" in received["stdin"]


# ---------------------------------------------------------------------------
# NOTE-010: unmeasured is not zero
# ---------------------------------------------------------------------------


def test_cli_usage_is_empty_not_zero(tmp_path: Path) -> None:
    fake = make_fake_cli(tmp_path, ECHO_BOTH)
    result = cli_agent.run_agent(cli_binding(str(fake)), system="", user="hi")

    assert result["usage"] == {}
    # A zero would read as "this route was free" in the usage rollup.
    assert "input_tokens" not in result["usage"]
    assert "output_tokens" not in result["usage"]


def test_cli_destination_is_the_binary(tmp_path: Path) -> None:
    fake = make_fake_cli(tmp_path, ECHO_BOTH)
    binding = cli_binding(str(fake))

    destination = dispatch.destination_of(binding)
    assert destination["targetBaseUrl"].endswith(fake.name)
    assert destination["targetModel"] == ""
    assert destination["targetModelSource"] == "cli-default"


def test_configured_model_is_reported_as_from_the_profile(tmp_path: Path) -> None:
    fake = make_fake_cli(tmp_path, ECHO_BOTH)
    destination = dispatch.destination_of(cli_binding(str(fake), model="chosen-model"))
    assert destination["targetModel"] == "chosen-model"
    assert destination["targetModelSource"] == "profile"


# ---------------------------------------------------------------------------
# Failure surfaces rather than being papered over
# ---------------------------------------------------------------------------


def test_missing_executable_names_what_is_missing() -> None:
    with pytest.raises(cli_agent.CliAgentError) as excinfo:
        cli_agent.run_agent(cli_binding("definitely-not-a-real-agent-xyz"), system="", user="hi")
    assert "definitely-not-a-real-agent-xyz" in str(excinfo.value)


def test_silent_success_is_treated_as_failure(tmp_path: Path) -> None:
    # exit 0 with no output is the shape a CLI takes when it needs a
    # non-interactive flag nobody passed. Treating it as an empty answer would
    # send an empty brief downstream.
    fake = make_fake_cli(tmp_path, "raise SystemExit(0)\n", name="silent-agent")
    with pytest.raises(cli_agent.CliAgentError) as excinfo:
        cli_agent.run_agent(cli_binding(str(fake)), system="", user="hi")
    assert "printed nothing" in str(excinfo.value)


def test_nonzero_exit_is_reported(tmp_path: Path) -> None:
    fake = make_fake_cli(tmp_path, "import sys; sys.exit(3)\n", name="failing-agent")
    with pytest.raises(cli_agent.CliAgentError) as excinfo:
        cli_agent.run_agent(cli_binding(str(fake)), system="", user="hi")
    assert "exited 3" in str(excinfo.value)


# ---------------------------------------------------------------------------
# NOTE-011: no silent downgrade
# ---------------------------------------------------------------------------


def test_dispatch_does_not_fall_back(tmp_path: Path) -> None:
    # NOTE(NOTE-011): a failure is handed back, not quietly served by someone
    # else. Auto-downgrade would keep the ledger green while quality dropped.
    calls: list[str] = []

    def counting_run(binding, system, user, timeout=None):
        calls.append(binding.command)
        raise cli_agent.CliAgentError("boom")

    original = cli_agent.run_agent
    cli_agent.run_agent = counting_run  # type: ignore[assignment]
    try:
        with pytest.raises(dispatch.DispatchError):
            dispatch.send(cli_binding("first-choice"), "sys", "user")
    finally:
        cli_agent.run_agent = original  # type: ignore[assignment]

    assert calls == ["first-choice"], "exactly one binding may be tried"


def test_json_retry_happens_once_then_gives_up(tmp_path: Path) -> None:
    attempts: list[str] = []

    def never_json(binding, system, user, timeout=None):
        attempts.append(system)
        return {"targetBaseUrl": "x", "targetModel": "", "text": "not json at all", "usage": {}}

    original = cli_agent.run_agent
    cli_agent.run_agent = never_json  # type: ignore[assignment]
    try:
        with pytest.raises(dispatch.DispatchError):
            dispatch.send_expecting_json(cli_binding("x"), "sys", "user", json.loads)
    finally:
        cli_agent.run_agent = original  # type: ignore[assignment]

    assert len(attempts) == 2, "one original attempt plus exactly one re-ask"
    assert dispatch.JSON_RETRY_INSTRUCTION in attempts[1]


def test_json_retry_recovers_a_chatty_agent(tmp_path: Path) -> None:
    replies = ["Sure! Here you go:\nnot valid", '{"ok": true}']

    def chatty(binding, system, user, timeout=None):
        return {"targetBaseUrl": "x", "targetModel": "", "text": replies.pop(0), "usage": {}}

    original = cli_agent.run_agent
    cli_agent.run_agent = chatty  # type: ignore[assignment]
    try:
        parsed, response = dispatch.send_expecting_json(cli_binding("x"), "sys", "user", json.loads)
    finally:
        cli_agent.run_agent = original  # type: ignore[assignment]

    assert parsed == {"ok": True}
    assert response["retriedForJson"] is True


# ---------------------------------------------------------------------------
# NOTE-012: which binary runs is never a conversational decision
# ---------------------------------------------------------------------------


def test_command_is_never_nl_writable() -> None:
    # NOTE(NOTE-012): with no confirmation gate on config changes, an injected
    # instruction that could set `command` would escalate F17 from "sends your
    # brief elsewhere" to "runs an arbitrary binary here".
    tool = [item for item in server.TOOLS if item["name"] == "profile_set_role"][0]
    properties = tool["inputSchema"]["properties"]
    for field in ("command", "args", "promptArg", "kind"):
        assert field not in properties, f"{field} must not be settable from a conversation"
        assert field not in server.NL_WRITABLE_FIELDS
        assert field not in profiles.WRITABLE_ROLE_FIELDS


def test_update_role_in_file_rejects_command(tmp_path: Path, monkeypatch) -> None:
    directory = tmp_path / "config"
    directory.mkdir()
    monkeypatch.setenv("DEV_TRIANGLE_CONFIG_DIR", str(directory))
    (directory / "providers.example.json").write_text(
        json.dumps({"schemaVersion": 1, "roles": {}}), encoding="utf-8"
    )
    with pytest.raises(profiles.ProfileError) as excinfo:
        profiles.update_role_in_file("example", "architect", {"command": "/bin/sh"})
    assert "command" in str(excinfo.value)


# ---------------------------------------------------------------------------
# architect-only finally has an entry point
# ---------------------------------------------------------------------------


@pytest.fixture()
def clean_ledger():
    if server.LEDGER_PATH.exists():
        server.LEDGER_PATH.unlink()
    yield
    if server.LEDGER_PATH.exists():
        server.LEDGER_PATH.unlink()


def test_architect_only_requires_source_paths(tmp_path: Path, clean_ledger) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(server.ToolError) as excinfo:
        server.tool_start_job({"repoPath": str(repo), "userRequest": "do a thing", "route": "architect-only"})
    assert "sourcePaths" in str(excinfo.value)


def test_architect_only_seeds_the_brief_from_the_caller(tmp_path: Path, clean_ledger) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "main.py").write_text("x\n", encoding="utf-8")

    result = server.tool_start_job(
        {
            "repoPath": str(repo),
            "userRequest": "do a thing",
            "route": "architect-only",
            "sourcePaths": ["src/main.py"],
        }
    )

    assert result["status"] == "OK"
    brief = result["job"]["contextBrief"]
    assert brief["sourceRefs"] == ["src/main.py"]
    assert brief["impactedFiles"] == ["src/main.py"]
    assert brief["author"] == "orchestrator"
    assert result["job"]["route"] == "architect-only"


def test_start_job_rejects_paths_that_do_not_exist(tmp_path: Path, clean_ledger) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(server.ToolError) as excinfo:
        server.tool_start_job(
            {
                "repoPath": str(repo),
                "userRequest": "do a thing",
                "route": "architect-only",
                "sourcePaths": ["src/nope.py"],
            }
        )
    assert "nope.py" in str(excinfo.value)


def test_local_route_needs_no_sources(tmp_path: Path, clean_ledger) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    result = server.tool_start_job({"repoPath": str(repo), "userRequest": "I will edit it myself", "route": "local"})
    assert result["job"]["route"] == "local"

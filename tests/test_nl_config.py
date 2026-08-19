# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 收集執行；import server 與 providers.profiles / providers.models；用 monkeypatch 把 DEV_TRIANGLE_CONFIG_DIR 指向 tmp_path，帳本走 conftest 的臨時 DEV_TRIANGLE_HOME
# 檔案路徑: dev-triangle-mcp/tests/test_nl_config.py
# 產生時間: 2026-08-19 14:20 +08:00
# 版本: v1.0
# 功能說明: 釘住「用講的改設定」這條路上的四道護欄——金鑰不得經過對話、幻覺模型 ID 不得寫入、七個角色以外不得生新的、以及每次變更都要大聲回報且可一句話還原
# 模組定位: W13 的突變驗證載體，也是 S4.10 四個量尺的牙齒。它「是」對設定寫入路徑的測試；它「不是」對設定讀取與解析的測試（那是 tests/test_provider_profile.py）
# 主要責任:
#   1. test_apikey_literal_rejected —— 守 INV-13、F13。這支是 secret_in_config_count 能不能算數的唯一依據
#   2. test_unknown_model_rejected / test_unlistable_provider_marks_unverified —— 守 INV-14 的兩條分支
#   3. test_unknown_slot_rejected —— 守 INV-11、F10
#   4. test_change_summary_always_returned —— 守 INV-15(a)。閘門拆掉之後，「使用者會不會看到」就是全部的防線
#   5. test_revert_writes_its_own_ledger_entry —— 守 INV-15(b)
# 維護提醒:
#   - 不得加任何「確認流程」的測試。擁有者已裁決設定變更不設閘門（gate #8、#9）；本檔要守的是「不留痕跡」不會發生，不是把閘門偷偷加回來
#   - 第 2 支與第 3 支必須同時存在。只測「對不到就拒絕」的話，一個永遠回 None 的 list_models 也會全綠
#   - canary 金鑰不得換成真的金鑰
# 驗證方式:
#   - python -m pytest -q tests\test_nl_config.py
# ------------------------------------------------------------

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import server
from providers import models, profiles


FAKE_MODEL = "<fake-model-for-test>"
KNOWN_MODEL = "listed-test-model"
CANARY_KEY_VALUE = "ghp_devTriangleCanary0000000000000000"


def base_roles() -> dict[str, Any]:
    return {
        "orchestrator": {"displayName": "", "kind": "mcp-client", "enabled": True},
        "contextBroker": {
            "displayName": "",
            "kind": "api",
            "provider": "",
            "dialect": "",
            "model": "",
            "baseUrl": "",
            "apiKeyEnv": "",
            "maxInputTokens": None,
            "enabled": False,
        },
        "architect": {
            "displayName": "",
            "kind": "api",
            "provider": "",
            "dialect": "",
            "model": "",
            "baseUrl": "",
            "apiKeyEnv": "",
            "maxInputTokens": None,
            "enabled": False,
        },
        "cloudWorker": {"displayName": "", "kind": "jules", "apiKeyEnv": "JULES_API_KEY", "enabled": True},
        "verifier": {"displayName": "", "kind": "local-suite", "enabled": True},
        "diagnostician": {"displayName": "", "kind": "cli", "command": "agy", "model": "", "enabled": True},
        "reporter": {"displayName": "", "kind": "mcp", "server": "dev-triangle-report", "enabled": True},
    }


@pytest.fixture()
def profile_env(tmp_path: Path, monkeypatch):
    directory = tmp_path / "config"
    directory.mkdir()
    payload = {"schemaVersion": 1, "displayName": "", "roles": base_roles()}
    (directory / "providers.example.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    monkeypatch.setenv("DEV_TRIANGLE_CONFIG_DIR", str(directory))
    monkeypatch.setenv("DEV_TRIANGLE_PROFILE", "example")
    models.clear_listers()
    if server.LEDGER_PATH.exists():
        server.LEDGER_PATH.unlink()
    yield directory
    models.clear_listers()
    if server.LEDGER_PATH.exists():
        server.LEDGER_PATH.unlink()


def stored_role(directory: Path, slot: str) -> dict[str, Any]:
    raw = json.loads((directory / "providers.example.json").read_text(encoding="utf-8"))
    return raw["roles"][slot]


def config_changes() -> list[dict[str, Any]]:
    return server.load_ledger().get("configChanges", [])


# ---------------------------------------------------------------------------
# INV-13 / F13: keys never travel through the conversation
# ---------------------------------------------------------------------------


def test_apikey_literal_rejected(profile_env: Path) -> None:
    with pytest.raises(server.ToolError) as excinfo:
        server.tool_profile_set_role(
            {"slot": "architect", "apiKeyEnv": CANARY_KEY_VALUE, "utterance": "my key is ..."}
        )

    message = str(excinfo.value)
    assert "Do not paste a key" in message
    assert "NAME" in message
    # S4.10 secret_in_config_count must stay 0: nothing was written anywhere.
    assert stored_role(profile_env, "architect")["apiKeyEnv"] == ""
    assert config_changes() == []


def test_secret_hidden_in_base_url_is_rejected(profile_env: Path) -> None:
    with pytest.raises(server.ToolError):
        server.tool_profile_set_role(
            {
                "slot": "architect",
                "baseUrl": f"https://proxy.invalid/v1?token={CANARY_KEY_VALUE}",
                "utterance": "use my proxy",
            }
        )
    assert stored_role(profile_env, "architect")["baseUrl"] == ""


def test_env_var_name_is_accepted(profile_env: Path) -> None:
    # The other branch: a plain variable name must go through.
    result = server.tool_profile_set_role(
        {"slot": "architect", "apiKeyEnv": "MY_ARCHITECT_KEY", "utterance": "use MY_ARCHITECT_KEY"}
    )
    assert result["status"] == "APPLIED"
    assert stored_role(profile_env, "architect")["apiKeyEnv"] == "MY_ARCHITECT_KEY"


# ---------------------------------------------------------------------------
# INV-14 / F14: hallucinated model ids
# ---------------------------------------------------------------------------


def test_unknown_model_rejected(profile_env: Path) -> None:
    models.register_lister("openai", lambda binding: [KNOWN_MODEL, "another-listed-model"])

    with pytest.raises(server.ToolError) as excinfo:
        server.tool_profile_set_role(
            {
                "slot": "architect",
                "dialect": "openai",
                "model": "the-newest-one-probably",
                "utterance": "use the newest one",
            }
        )

    message = str(excinfo.value)
    assert "not offered" in message
    assert KNOWN_MODEL in message, "the user needs the real options, not just a refusal"
    assert stored_role(profile_env, "architect")["model"] == ""


def test_known_model_is_marked_verified(profile_env: Path) -> None:
    models.register_lister("openai", lambda binding: [KNOWN_MODEL])

    result = server.tool_profile_set_role(
        {"slot": "architect", "dialect": "openai", "model": KNOWN_MODEL, "utterance": f"use {KNOWN_MODEL}"}
    )

    assert result["changeSummary"]["verified"] is True
    assert stored_role(profile_env, "architect")["verified"] is True


def test_unlistable_provider_marks_unverified(profile_env: Path) -> None:
    # INV-14 second branch. Only testing the first would leave this permanently
    # green, and "cannot verify" would quietly become "verified".
    result = server.tool_profile_set_role(
        {"slot": "architect", "model": FAKE_MODEL, "utterance": f"use {FAKE_MODEL}"}
    )

    assert result["changeSummary"]["verified"] is False
    assert stored_role(profile_env, "architect")["verified"] is False
    assert stored_role(profile_env, "architect")["model"] == FAKE_MODEL
    assert "unverified" in result["message"]


# ---------------------------------------------------------------------------
# INV-11 / F10: seven slots, no more
# ---------------------------------------------------------------------------


def test_unknown_slot_rejected(profile_env: Path) -> None:
    with pytest.raises(server.ToolError) as excinfo:
        server.tool_profile_set_role(
            {"slot": "reviewer", "model": FAKE_MODEL, "utterance": "add a reviewer role"}
        )

    message = str(excinfo.value)
    assert "seven" in message
    assert "contextBroker" in message, "tell the user what does exist"
    raw = json.loads((profile_env / "providers.example.json").read_text(encoding="utf-8"))
    assert "reviewer" not in raw["roles"]
    assert config_changes() == []


def test_structural_fields_cannot_be_rewritten(profile_env: Path) -> None:
    # kind picks the adapter. Letting a conversation change it points the slot
    # at code that does not exist.
    tool = [item for item in server.TOOLS if item["name"] == "profile_set_role"][0]
    assert "kind" not in tool["inputSchema"]["properties"]
    with pytest.raises(profiles.ProfileError):
        profiles.update_role_in_file("example", "architect", {"kind": "api"})


# ---------------------------------------------------------------------------
# INV-15(a): never gated, never silent
# ---------------------------------------------------------------------------


def test_change_summary_always_returned(profile_env: Path) -> None:
    # This is F17's only detection surface. With no gate, whether the user sees
    # the change is the entire defence.
    cases = [
        {"slot": "architect", "displayName": "首席架構師", "utterance": "call it 首席架構師"},
        {"slot": "architect", "model": FAKE_MODEL, "utterance": f"use {FAKE_MODEL}"},
        {"slot": "contextBroker", "baseUrl": "https://example.invalid/v1", "utterance": "use my endpoint"},
        {"slot": "architect", "provider": "someone", "utterance": "switch provider"},
    ]
    for case in cases:
        result = server.tool_profile_set_role(case)
        summary = result["changeSummary"]
        assert summary, f"no changeSummary for {case}"
        assert summary["slot"] == case["slot"]
        assert "before" in summary and "after" in summary
        assert "scope" in summary and "permanent" in summary
        assert result["status"] != "NEEDS_CONFIRMATION"
        assert result["message"].strip()


def test_scope_defaults_to_permanent_and_says_so(profile_env: Path) -> None:
    result = server.tool_profile_set_role(
        {"slot": "architect", "model": FAKE_MODEL, "utterance": f"switch to {FAKE_MODEL}"}
    )
    assert result["changeSummary"]["scope"] == "profile"
    assert result["changeSummary"]["permanent"] is True
    assert "permanent" in result["message"].lower()
    assert "only wanted it for this one job" in result["message"]


def test_base_url_change_is_flagged_loudly(profile_env: Path) -> None:
    result = server.tool_profile_set_role(
        {"slot": "architect", "baseUrl": "https://somewhere-else.invalid/v1", "utterance": "point it there"}
    )
    assert result["warnings"], "an endpoint change must be shouted about"
    assert result["message"].startswith("ATTENTION")
    assert "somewhere-else.invalid" in result["message"]


def test_this_job_scope_leaves_the_file_alone(profile_env: Path) -> None:
    job = server.upsert_job(server.new_job_skeleton(provider="dev-triangle", route="local"))
    result = server.tool_profile_set_role(
        {
            "slot": "architect",
            "model": FAKE_MODEL,
            "scope": "thisJob",
            "jobId": job["id"],
            "utterance": "just this once",
        }
    )
    assert result["changeSummary"]["permanent"] is False
    assert stored_role(profile_env, "architect")["model"] == ""
    stored_job = server.tool_job_get({"jobId": job["id"]})["job"]
    assert stored_job["roleBindings"]["architect"]["model"] == FAKE_MODEL


def test_utterance_is_required(profile_env: Path) -> None:
    # Without it there is no answer to "why was it using that model in July".
    with pytest.raises(server.ToolError):
        server.tool_profile_set_role({"slot": "architect", "model": FAKE_MODEL})


def test_every_change_is_logged_with_the_words_that_caused_it(profile_env: Path) -> None:
    server.tool_profile_set_role(
        {"slot": "architect", "model": FAKE_MODEL, "utterance": "換成那個便宜的"}
    )
    changes = config_changes()
    assert len(changes) == 1
    assert changes[0]["utterance"] == "換成那個便宜的"
    assert changes[0]["utteranceSource"] == "agent_reported"
    assert changes[0]["scope"] == "profile"
    # S4.10 unlogged_config_change_count = 0
    assert changes[0]["after"]["model"] == FAKE_MODEL


# ---------------------------------------------------------------------------
# INV-15(b): one sentence undoes it, and the undo is booked too
# ---------------------------------------------------------------------------


def test_revert_writes_its_own_ledger_entry(profile_env: Path) -> None:
    server.tool_profile_set_role(
        {"slot": "architect", "model": FAKE_MODEL, "utterance": "use the fake one"}
    )
    assert stored_role(profile_env, "architect")["model"] == FAKE_MODEL

    result = server.tool_profile_revert_last({"utterance": "undo that"})

    assert result["status"] == "REVERTED"
    assert stored_role(profile_env, "architect")["model"] == ""
    changes = config_changes()
    assert len(changes) == 2, "the revert must book itself, or the audit will not add up"
    assert changes[-1]["reverts"] == changes[0]["id"]
    assert changes[-1]["utterance"] == "undo that"


def test_revert_with_nothing_to_revert(profile_env: Path) -> None:
    assert server.tool_profile_revert_last({})["status"] == "NOTHING_TO_REVERT"


def test_describe_reports_bindings_and_history(profile_env: Path) -> None:
    server.tool_profile_set_role(
        {"slot": "architect", "model": FAKE_MODEL, "utterance": "use the fake one"}
    )
    described = server.tool_profile_describe({})
    assert described["name"] == "example"
    assert "contextBroker" in described["unresolvedRoles"]
    assert described["unverifiedModelSlots"] == ["architect"]
    assert described["configChanges"][-1]["utterance"] == "use the fake one"


# ---------------------------------------------------------------------------
# W15: switching the whole profile at once
# ---------------------------------------------------------------------------


def write_second_profile(directory: Path, name: str = "cheap") -> None:
    roles = base_roles()
    roles["architect"].update({"enabled": True, "apiKeyEnv": "SOME_KEY", "model": FAKE_MODEL})
    (directory / f"providers.{name}.json").write_text(
        json.dumps({"schemaVersion": 1, "displayName": "", "roles": roles}, indent=2), encoding="utf-8"
    )


def test_activate_switches_and_persists(profile_env: Path) -> None:
    write_second_profile(profile_env)

    result = server.tool_profile_activate({"profile": "cheap", "utterance": "gemini 額度用完了，換 cheap"})

    assert result["status"] == "ACTIVATED"
    assert result["changeSummary"]["after"] == "cheap"
    assert result["changeSummary"]["before"] == "example"
    # Persisted, not just set in this process: a long-running MCP server cannot
    # see an env var that changed after it started.
    assert (profile_env / "active-profile.json").exists()
    assert profiles.active_profile_name() == "cheap"


def test_file_beats_the_environment_variable(profile_env: Path, monkeypatch) -> None:
    write_second_profile(profile_env)
    monkeypatch.setenv("DEV_TRIANGLE_PROFILE", "example")

    server.tool_profile_activate({"profile": "cheap", "utterance": "switch"})

    name, source = profiles.active_profile_source()
    assert (name, source) == ("cheap", "file"), "otherwise switching appears to do nothing"


def test_health_check_says_which_source_won(profile_env: Path) -> None:
    write_second_profile(profile_env)
    assert server.profile_health_block()["activeProfileSource"] == "env"

    server.tool_profile_activate({"profile": "cheap", "utterance": "switch"})
    block = server.profile_health_block()
    assert block["activeProfile"] == "cheap"
    assert block["activeProfileSource"] == "file"


def test_activate_rejects_an_unknown_profile(profile_env: Path) -> None:
    with pytest.raises(server.ToolError) as excinfo:
        server.tool_profile_activate({"profile": "not-a-profile", "utterance": "switch"})
    assert "example" in str(excinfo.value), "list what does exist"


def test_activate_is_logged_with_the_utterance(profile_env: Path) -> None:
    write_second_profile(profile_env)
    server.tool_profile_activate({"profile": "cheap", "utterance": "換成便宜那組"})

    change = config_changes()[-1]
    assert change["scope"] == "activeProfile"
    assert change["utterance"] == "換成便宜那組"
    assert change["before"]["activeProfile"] == "example"
    assert change["after"]["activeProfile"] == "cheap"


def test_activate_reports_which_roles_are_still_unconfigured(profile_env: Path) -> None:
    write_second_profile(profile_env)
    result = server.tool_profile_activate({"profile": "cheap", "utterance": "switch"})
    assert "contextBroker" in result["message"]


def test_revert_switches_the_profile_back(profile_env: Path) -> None:
    write_second_profile(profile_env)
    server.tool_profile_activate({"profile": "cheap", "utterance": "switch"})
    assert profiles.active_profile_name() == "cheap"

    result = server.tool_profile_revert_last({"profile": "cheap", "utterance": "undo that"})

    assert result["status"] == "REVERTED"
    assert profiles.active_profile_name() == "example"
    assert config_changes()[-1]["reverts"]


def test_revert_declines_rather_than_leaving_no_profile(profile_env: Path, monkeypatch) -> None:
    # Undoing back to "no profile at all" would make every role unreachable,
    # which is worse than where the user already is.
    monkeypatch.delenv("DEV_TRIANGLE_PROFILE", raising=False)
    write_second_profile(profile_env)
    server.tool_profile_activate({"profile": "cheap", "utterance": "switch"})

    result = server.tool_profile_revert_last({"profile": "cheap", "utterance": "undo that"})

    assert result["reverted"][0]["skipped"]
    assert profiles.active_profile_name() == "cheap"


def test_no_confirmation_path_exists() -> None:
    # Owner ruling gate #8/#9: this tool never gates. Asserted on the schema so
    # a future "just one small confirm flag" shows up here.
    tool = [item for item in server.TOOLS if item["name"] == "profile_set_role"][0]
    assert "confirm" not in json.dumps(tool["inputSchema"]).lower()

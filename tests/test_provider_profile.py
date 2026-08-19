# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 收集執行；import providers.profiles 與 server；用 monkeypatch 把 DEV_TRIANGLE_CONFIG_DIR 指向 tmp_path，不讀也不寫 repo 裡真正的 config/
# 檔案路徑: dev-triangle-mcp/tests/test_provider_profile.py
# 產生時間: 2026-08-19 12:05 +08:00
# 版本: v1.0
# 功能說明: 釘住「本專案永遠不替使用者挑模型」這件事。每一支測試對應一種讓它悄悄失效的寫法——回預設 profile、加一個 or 內建值、改掉 slot key、把金鑰當成環境變數名寫進去
# 模組定位: W01 的突變驗證載體，也是 S4.9 silent_default_count = 0 這條量尺的牙齒。它「是」設定載入與解析的單元測試；它「不是」對 adapter 實際呼叫外部 API 的測試
# 主要責任:
#   1. test_missing_profile_raises_not_default —— 守 INV-12（找不到不得回預設）
#   2. test_empty_model_never_falls_back —— 守 F11（空模型不得有 fallback）
#   3. test_missing_slot_key_rejected —— 守 INV-11、F10（slot key 不可更名）
#   4. test_api_key_env_rejects_literal_secret —— 守 INV-04（只收環境變數名）
#   5. test_agy_model_has_no_hardcoded_fallback —— 守 S6 記載的既有違規不復發
#   6. test_cli_role_allows_empty_model —— 守 NOTE-004 的另一條分支
#   7. test_broken_profile_surfaces_as_note_not_crash —— 守 NOTE-005
# 維護提醒:
#   - 不得在本檔任何 fixture 填入真實模型名。S4.8 的掃描會命中，用 <fake-model-for-test> 之類的假值
#   - 第 2 支與第 6 支必須同時存在。只留其中一支的話，把 resolve_role 的 kind 判斷拿掉會有一半機率仍然全綠（SAI I0.3）
#   - 不得為了讓測試好寫而放寬 load_profile 的驗證。這裡每一條驗證擋的都是「不會有任何測試變紅」的無聲失效
# 驗證方式:
#   - python -m pytest -q tests\test_provider_profile.py
# ------------------------------------------------------------

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import server
from providers import profiles


FAKE_MODEL = "<fake-model-for-test>"
FAKE_KEY_ENV = "DEV_TRIANGLE_TEST_BROKER_KEY"
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
def config_dir(tmp_path: Path, monkeypatch) -> Path:
    directory = tmp_path / "config"
    directory.mkdir()
    monkeypatch.setenv("DEV_TRIANGLE_CONFIG_DIR", str(directory))
    monkeypatch.delenv("DEV_TRIANGLE_PROFILE", raising=False)
    monkeypatch.delenv("ANTIGRAVITY_AGY_MODEL", raising=False)
    return directory


def write_profile(directory: Path, name: str, roles: dict[str, Any] | None = None, **extra: Any) -> Path:
    payload: dict[str, Any] = {"schemaVersion": 1, "displayName": "", "roles": roles or base_roles()}
    payload.update(extra)
    path = directory / f"providers.{name}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# 1. INV-12: no default profile
# --------------------------------------------------------------------------


def test_missing_profile_raises_not_default(config_dir: Path) -> None:
    write_profile(config_dir, "alpha")
    write_profile(config_dir, "beta")

    with pytest.raises(profiles.ProfileNotFound) as excinfo:
        profiles.load_profile("does-not-exist")

    message = str(excinfo.value)
    assert "alpha" in message and "beta" in message, "the error must list what is actually available"


def test_list_profiles_uses_the_file_name_as_the_profile_name(config_dir: Path) -> None:
    write_profile(config_dir, "cheap")
    write_profile(config_dir, "careful")
    assert profiles.list_profiles() == ["careful", "cheap"]


# --------------------------------------------------------------------------
# 2. F11: empty model never falls back
# --------------------------------------------------------------------------


def test_empty_model_never_falls_back(config_dir: Path, monkeypatch) -> None:
    roles = base_roles()
    roles["architect"].update({"enabled": True, "apiKeyEnv": FAKE_KEY_ENV, "model": ""})
    write_profile(config_dir, "example", roles)
    monkeypatch.setenv(FAKE_KEY_ENV, "not-a-real-key")

    profile = profiles.load_profile("example")
    with pytest.raises(profiles.RoleNotConfigured) as excinfo:
        profiles.resolve_role(profile, "architect")

    assert "ROLE_NOT_CONFIGURED" in str(excinfo.value)
    assert "roles.architect.model" in str(excinfo.value), "the error must say which line to fill"


def test_configured_api_role_resolves(config_dir: Path, monkeypatch) -> None:
    # The other branch: a fully configured role must actually work, otherwise
    # "always raise" would pass every test above.
    roles = base_roles()
    roles["architect"].update({"enabled": True, "apiKeyEnv": FAKE_KEY_ENV, "model": FAKE_MODEL})
    write_profile(config_dir, "example", roles)
    monkeypatch.setenv(FAKE_KEY_ENV, "not-a-real-key")

    binding = profiles.resolve_role(profiles.load_profile("example"), "architect")
    assert binding.model == FAKE_MODEL
    assert binding.configured is True


def test_missing_api_key_env_value_is_not_configured(config_dir: Path, monkeypatch) -> None:
    roles = base_roles()
    roles["architect"].update({"enabled": True, "apiKeyEnv": FAKE_KEY_ENV, "model": FAKE_MODEL})
    write_profile(config_dir, "example", roles)
    monkeypatch.delenv(FAKE_KEY_ENV, raising=False)

    with pytest.raises(profiles.RoleNotConfigured):
        profiles.resolve_role(profiles.load_profile("example"), "architect")


def test_disabled_role_refuses_instead_of_calling(config_dir: Path) -> None:
    write_profile(config_dir, "example")
    with pytest.raises(profiles.RoleDisabled) as excinfo:
        profiles.resolve_role(profiles.load_profile("example"), "contextBroker")
    assert "ROLE_DISABLED" in str(excinfo.value)


# --------------------------------------------------------------------------
# 3. INV-11 / F10: slot keys are the contract
# --------------------------------------------------------------------------


def test_missing_slot_key_rejected(config_dir: Path) -> None:
    roles = base_roles()
    # The realistic shape of F10: renamed, not deleted.
    roles["broker"] = roles.pop("contextBroker")
    write_profile(config_dir, "example", roles)

    with pytest.raises(profiles.ProfileError) as excinfo:
        profiles.load_profile("example")

    message = str(excinfo.value)
    assert "contextBroker" in message
    assert "broker" in message
    assert "displayName" in message, "the error must point at the supported way to rename"


def test_display_name_is_never_validated(config_dir: Path) -> None:
    # displayName is the user's free area: any language, emoji, blank, repeated.
    roles = base_roles()
    roles["contextBroker"]["displayName"] = "情報官 🛰️"
    roles["architect"]["displayName"] = "情報官 🛰️"
    write_profile(config_dir, "example", roles)

    profile = profiles.load_profile("example")
    assert profile.roles["contextBroker"].display_name == "情報官 🛰️"
    assert profile.roles["architect"].display_name == "情報官 🛰️"


def test_unknown_kind_rejected(config_dir: Path) -> None:
    roles = base_roles()
    roles["architect"]["kind"] = "my-own-adapter"
    write_profile(config_dir, "example", roles)

    with pytest.raises(profiles.ProfileError) as excinfo:
        profiles.load_profile("example")
    assert "kind" in str(excinfo.value)


def test_new_slots_cannot_be_resolved(config_dir: Path) -> None:
    write_profile(config_dir, "example")
    with pytest.raises(profiles.ProfileError) as excinfo:
        profiles.resolve_role(profiles.load_profile("example"), "reviewer")
    assert "seven" in str(excinfo.value)


# --------------------------------------------------------------------------
# 4. INV-04: apiKeyEnv is a name, not a key
# --------------------------------------------------------------------------


def test_api_key_env_rejects_literal_secret(config_dir: Path) -> None:
    roles = base_roles()
    roles["architect"]["apiKeyEnv"] = CANARY_KEY_VALUE
    write_profile(config_dir, "example", roles)

    with pytest.raises(profiles.ProfileError) as excinfo:
        profiles.load_profile("example")

    message = str(excinfo.value)
    assert "credential" in message.lower()
    assert "NAME" in message, "the message has to tell the user what to do instead"


def test_api_key_env_rejects_lowercase_name(config_dir: Path) -> None:
    roles = base_roles()
    roles["architect"]["apiKeyEnv"] = "my_broker_key"
    write_profile(config_dir, "example", roles)
    with pytest.raises(profiles.ProfileError):
        profiles.load_profile("example")


def test_api_key_env_accepts_a_plain_name(config_dir: Path) -> None:
    roles = base_roles()
    roles["architect"]["apiKeyEnv"] = FAKE_KEY_ENV
    write_profile(config_dir, "example", roles)
    profile = profiles.load_profile("example")
    assert profile.roles["architect"].api_key_env == FAKE_KEY_ENV


# --------------------------------------------------------------------------
# 5. S6's pre-existing violation must not come back
# --------------------------------------------------------------------------


def test_agy_model_has_no_hardcoded_fallback(config_dir: Path, monkeypatch) -> None:
    # No env var, no profile: the correct answer is "no model", which means
    # "do not pass --model", not "here is one I picked".
    monkeypatch.delenv("ANTIGRAVITY_AGY_MODEL", raising=False)
    monkeypatch.delenv("DEV_TRIANGLE_PROFILE", raising=False)

    model, note = server.configured_antigravity_agy_model()
    assert model == ""
    assert note is None


def test_agy_model_comes_from_the_profile_when_env_is_unset(config_dir: Path, monkeypatch) -> None:
    roles = base_roles()
    roles["diagnostician"]["model"] = FAKE_MODEL
    write_profile(config_dir, "example", roles)
    monkeypatch.delenv("ANTIGRAVITY_AGY_MODEL", raising=False)
    monkeypatch.setenv("DEV_TRIANGLE_PROFILE", "example")

    model, note = server.configured_antigravity_agy_model()
    assert model == FAKE_MODEL
    assert note is None


def test_env_var_wins_over_the_profile(config_dir: Path, monkeypatch) -> None:
    roles = base_roles()
    roles["diagnostician"]["model"] = FAKE_MODEL
    write_profile(config_dir, "example", roles)
    monkeypatch.setenv("DEV_TRIANGLE_PROFILE", "example")
    monkeypatch.setenv("ANTIGRAVITY_AGY_MODEL", "env-wins-model")

    model, _ = server.configured_antigravity_agy_model()
    assert model == "env-wins-model"


# --------------------------------------------------------------------------
# 6. NOTE-004: cli roles are allowed to leave model empty
# --------------------------------------------------------------------------


def test_cli_role_allows_empty_model(config_dir: Path, monkeypatch) -> None:
    # NOTE(NOTE-004): empty here means "do not pass --model", not "unconfigured".
    write_profile(config_dir, "example")
    monkeypatch.setenv("DEV_TRIANGLE_PROFILE", "example")

    binding = profiles.resolve_role(profiles.load_profile("example"), "diagnostician")
    assert binding.model == ""
    assert binding.configured is True


# --------------------------------------------------------------------------
# 7. NOTE-005: a broken profile is reported, not swallowed, and not fatal here
# --------------------------------------------------------------------------


def test_broken_profile_surfaces_as_note_not_crash(config_dir: Path, monkeypatch) -> None:
    roles = base_roles()
    roles["broker"] = roles.pop("contextBroker")
    write_profile(config_dir, "example", roles)
    monkeypatch.setenv("DEV_TRIANGLE_PROFILE", "example")
    monkeypatch.delenv("ANTIGRAVITY_AGY_MODEL", raising=False)

    # The loader itself must be strict.
    with pytest.raises(profiles.ProfileError):
        profiles.load_profile("example")

    # The diagnostic path must still answer, and must say what is wrong.
    model, note = server.configured_antigravity_agy_model()
    assert model == ""
    assert note is not None and "contextBroker" in note


def test_health_check_reports_profile_error(config_dir: Path, monkeypatch) -> None:
    roles = base_roles()
    roles["broker"] = roles.pop("contextBroker")
    write_profile(config_dir, "example", roles)
    monkeypatch.setenv("DEV_TRIANGLE_PROFILE", "example")

    block = server.profile_health_block()
    assert block["status"] == "PROFILE_ERROR"
    assert "contextBroker" in block["error"]


def test_health_check_reports_no_profile_selected(config_dir: Path, monkeypatch) -> None:
    write_profile(config_dir, "example")
    monkeypatch.delenv("DEV_TRIANGLE_PROFILE", raising=False)

    block = server.profile_health_block()
    assert block["status"] == "NO_PROFILE_SELECTED"
    assert "example" in block["availableProfiles"]


# --------------------------------------------------------------------------
# A4.4 rule 2 / F12: two slots on one model is legal but must be visible
# --------------------------------------------------------------------------


def test_shared_model_slots_are_reported(config_dir: Path) -> None:
    roles = base_roles()
    for slot in ("contextBroker", "architect"):
        roles[slot].update({"enabled": True, "apiKeyEnv": FAKE_KEY_ENV, "model": FAKE_MODEL})
    write_profile(config_dir, "example", roles)

    described = profiles.load_profile("example").describe()
    shared = described["sharedModelSlots"]
    assert len(shared) == 1
    assert sorted(shared[0]["slots"]) == ["architect", "contextBroker"]


def test_unconfigured_roles_are_listed(config_dir: Path) -> None:
    write_profile(config_dir, "example")
    described = profiles.load_profile("example").describe()
    assert sorted(described["unresolvedRoles"]) == ["architect", "contextBroker"]
    assert described["unresolvedRoleCount"] == 2

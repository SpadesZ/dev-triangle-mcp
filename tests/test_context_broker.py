# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 收集執行；import server 與 providers.context_broker / outbound / http；用 monkeypatch 換掉 http.chat，不發任何真實網路請求
# 檔案路徑: dev-triangle-mcp/tests/test_context_broker.py
# 產生時間: 2026-08-19 15:35 +08:00
# 版本: v1.0
# 功能說明: 釘住第一棒外送前的三道檢查——repo 要在白名單裡、payload 要過遮罩、回來的檔案路徑要真的存在；以及回傳一定要講出東西被送去哪
# 模組定位: W05 的突變驗證載體，守 INV-06、S4.3 與 INV-15(c)。它「是」對外送路徑的測試；它「不是」對真實模型輸出品質的測試（那要真的金鑰，屬於 C6）
# 主要責任:
#   1. test_payload_goes_through_redaction —— 繞過 W08 直送必須變紅
#   2. test_impacted_files_must_exist —— 回傳不存在的路徑必須變紅
#   3. test_dispatch_must_include_target_destination —— 隱藏去向必須變紅（守 INV-15c、F17）
#   4. test_repo_not_in_allowlist_is_refused —— 守 owner gate #3 的 fail-closed
# 維護提醒:
#   - 不得把 impactedFiles 的存在性檢查改成「過濾掉不存在的」。過濾會讓 S4.3 的 recall 看起來很漂亮，而那正是它要抓的失效
#   - fake 的 http.chat 不得改成真的呼叫。這裡只驗證護欄，C6「not only mocks」要另外用真的金鑰跑
# 驗證方式:
#   - python -m pytest -q tests\test_context_broker.py
# ------------------------------------------------------------

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import server
from providers import context_broker, http, outbound


FAKE_MODEL = "<fake-model-for-test>"
KEY_ENV = "DEV_TRIANGLE_TEST_BROKER_KEY"
CANARY_KEY = "ghp_devTriangleCanary0000000000000000"


def roles_with_broker() -> dict[str, Any]:
    return {
        "orchestrator": {"displayName": "", "kind": "mcp-client", "enabled": True},
        "contextBroker": {
            "displayName": "情報官",
            "kind": "api",
            "provider": "test",
            "dialect": "openai",
            "model": FAKE_MODEL,
            "baseUrl": "https://broker.invalid/v1",
            "apiKeyEnv": KEY_ENV,
            "maxInputTokens": None,
            "enabled": True,
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
def broker_env(tmp_path: Path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / "providers.example.json").write_text(
        json.dumps({"schemaVersion": 1, "displayName": "", "roles": roles_with_broker()}, indent=2),
        encoding="utf-8",
    )
    repo = tmp_path / "target-repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (repo / "README.md").write_text("readme\n", encoding="utf-8")
    (config / "outbound-repos.json").write_text(
        json.dumps({"schemaVersion": 1, "allowedRepos": [str(repo)]}, indent=2), encoding="utf-8"
    )
    monkeypatch.setenv("DEV_TRIANGLE_CONFIG_DIR", str(config))
    monkeypatch.setenv("DEV_TRIANGLE_PROFILE", "example")
    monkeypatch.setenv(KEY_ENV, "not-a-real-key")
    if server.LEDGER_PATH.exists():
        server.LEDGER_PATH.unlink()
    yield repo, config
    if server.LEDGER_PATH.exists():
        server.LEDGER_PATH.unlink()


def fake_chat(payload: dict[str, Any], sent: list[dict[str, str]]):
    def _chat(binding, system, user, timeout=None):
        sent.append({"system": system, "user": user})
        return {
            "targetBaseUrl": binding.base_url,
            "targetModel": binding.model,
            "text": json.dumps(payload),
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }

    return _chat


def good_payload() -> dict[str, Any]:
    return {
        "repoSummary": "a tiny repo",
        "impactedFiles": ["src/main.py"],
        "keyDependencies": ["python"],
        "sourceRefs": ["README.md"],
    }


# ---------------------------------------------------------------------------
# INV-06: nothing leaves without passing the mask
# ---------------------------------------------------------------------------


def test_payload_goes_through_redaction(broker_env, monkeypatch) -> None:
    repo, _ = broker_env
    (repo / "leaky.md").write_text(f"deploy token {CANARY_KEY}\n", encoding="utf-8")
    sent: list[dict[str, str]] = []
    monkeypatch.setattr(http, "chat", fake_chat(good_payload(), sent))

    # The outline itself carries the file name, but the canary is in the body,
    # so use a request that quotes it: that is the realistic leak shape.
    result = server.tool_dispatch_context_brief(
        {"repoPath": str(repo), "userRequest": f"the failing log said {CANARY_KEY}"}
    )

    assert result["status"] == "OUTBOUND_BLOCKED"
    assert sent == [], "nothing may be sent when the payload trips the scanner"


def test_home_paths_are_masked_before_sending(broker_env, monkeypatch) -> None:
    repo, _ = broker_env
    sent: list[dict[str, str]] = []
    monkeypatch.setattr(http, "chat", fake_chat(good_payload(), sent))
    import os

    home = os.environ.get("USERPROFILE") or str(Path.home())

    server.tool_dispatch_context_brief({"repoPath": str(repo), "userRequest": f"look at {home}\\thing"})

    assert sent, "a clean payload must actually be sent"
    assert home not in sent[0]["user"]
    assert "<HOME>" in sent[0]["user"]


# ---------------------------------------------------------------------------
# owner gate #3: fail-closed repo allowlist
# ---------------------------------------------------------------------------


def test_repo_not_in_allowlist_is_refused(broker_env, monkeypatch, tmp_path: Path) -> None:
    _, config = broker_env
    other = tmp_path / "someone-elses-repo"
    other.mkdir()
    (other / "a.py").write_text("x\n", encoding="utf-8")
    sent: list[dict[str, str]] = []
    monkeypatch.setattr(http, "chat", fake_chat(good_payload(), sent))

    result = server.tool_dispatch_context_brief({"repoPath": str(other), "userRequest": "do a thing"})

    assert result["status"] == "OUTBOUND_BLOCKED"
    assert "OUTBOUND_NOT_ALLOWED" in result["message"]
    assert sent == []


def test_empty_allowlist_allows_nothing(broker_env, monkeypatch) -> None:
    repo, config = broker_env
    (config / "outbound-repos.json").write_text(
        json.dumps({"schemaVersion": 1, "allowedRepos": []}), encoding="utf-8"
    )
    assert outbound.allowed_repos() == []
    assert outbound.is_allowed(repo) is False


# ---------------------------------------------------------------------------
# S4.3: a brief that names files which do not exist is rejected, not trimmed
# ---------------------------------------------------------------------------


def test_impacted_files_must_exist(broker_env, monkeypatch) -> None:
    repo, _ = broker_env
    payload = good_payload()
    payload["impactedFiles"] = ["src/main.py", "src/does_not_exist.py"]
    monkeypatch.setattr(http, "chat", fake_chat(payload, []))

    result = server.tool_dispatch_context_brief({"repoPath": str(repo), "userRequest": "do a thing"})

    assert result["status"] == "BRIEF_REJECTED"
    assert "does_not_exist.py" in result["message"]


def test_empty_impacted_files_is_rejected(broker_env, monkeypatch) -> None:
    payload = good_payload()
    payload["impactedFiles"] = []
    repo, _ = broker_env
    monkeypatch.setattr(http, "chat", fake_chat(payload, []))

    result = server.tool_dispatch_context_brief({"repoPath": str(repo), "userRequest": "do a thing"})
    assert result["status"] == "BRIEF_REJECTED"


# ---------------------------------------------------------------------------
# INV-15(c) / F17: the user has to see where their code went
# ---------------------------------------------------------------------------


def test_dispatch_must_include_target_destination(broker_env, monkeypatch) -> None:
    repo, _ = broker_env
    monkeypatch.setattr(http, "chat", fake_chat(good_payload(), []))

    result = server.tool_dispatch_context_brief({"repoPath": str(repo), "userRequest": "do a thing"})

    assert result["status"] == "OK"
    assert result["dispatch"]["targetBaseUrl"] == "https://broker.invalid/v1"
    assert result["dispatch"]["targetModel"] == FAKE_MODEL
    # And in the stored record, not only in the immediate reply.
    assert result["contextBrief"]["targetBaseUrl"] == "https://broker.invalid/v1"
    assert result["contextBrief"]["targetModel"] == FAKE_MODEL
    assert "broker.invalid" in result["message"]

    stored = server.tool_job_get({"jobId": result["jobId"]})["job"]
    assert stored["contextBrief"]["targetBaseUrl"] == "https://broker.invalid/v1"


def test_unconfigured_role_refuses_without_calling(broker_env, monkeypatch) -> None:
    repo, config = broker_env
    roles = roles_with_broker()
    roles["contextBroker"]["model"] = ""
    (config / "providers.example.json").write_text(
        json.dumps({"schemaVersion": 1, "displayName": "", "roles": roles}, indent=2), encoding="utf-8"
    )
    sent: list[dict[str, str]] = []
    monkeypatch.setattr(http, "chat", fake_chat(good_payload(), sent))

    result = server.tool_dispatch_context_brief({"repoPath": str(repo), "userRequest": "do a thing"})

    assert result["status"] == "ROLE_NOT_CONFIGURED"
    assert sent == []


# ---------------------------------------------------------------------------
# Size ceiling
# ---------------------------------------------------------------------------


def test_brief_is_capped(broker_env, monkeypatch) -> None:
    repo, _ = broker_env
    payload = good_payload()
    payload["repoSummary"] = "x" * (context_broker.MAX_BRIEF_CHARS + 5000)
    monkeypatch.setattr(http, "chat", fake_chat(payload, []))

    result = server.tool_dispatch_context_brief({"repoPath": str(repo), "userRequest": "do a thing"})

    brief = result["contextBrief"]
    assert brief["truncated"] is True
    assert len(json.dumps(brief, ensure_ascii=False)) <= context_broker.MAX_BRIEF_CHARS + 500
    # The files survive the cut; the prose is what gets shortened.
    assert brief["impactedFiles"] == ["src/main.py"]

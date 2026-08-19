# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 收集執行；import server 與 providers.architect / http；在 tmp_path 建真的 git repo 與 verify.json，用 monkeypatch 換掉 http.chat
# 檔案路徑: dev-triangle-mcp/tests/test_self_heal.py
# 產生時間: 2026-08-19 16:50 +08:00
# 版本: v1.0
# 功能說明: 釘住自動重試的兩道煞車——次數硬上限，以及回送的錯誤 log 必須先過遮罩。錯誤 log 是本專案唯一一條由 repo 內容決定、又會自動往外送的資料
# 模組定位: W07 的突變驗證載體，守 INV-08 與 F5、F3。它「是」對重試邊界的測試；它「不是」對修復品質的測試
# 主要責任:
#   1. test_attempts_hard_capped —— 守 INV-08。profile 想調多高都不行
#   2. test_error_log_is_redacted —— 在 stderr 種 canary，未遮罩就送必須變紅
#   3. test_cost_is_recorded_every_attempt —— 沒有成本欄位的自動重試是沒有煞車的迴圈
#   4. test_suite_is_never_changed_between_attempts —— 改 suite 讓測試變綠是最典型的假綠燈
# 維護提醒:
#   - 上限是寫在程式碼裡的 SELF_HEAL_HARD_CAP，不得改成可由設定檔覆寫。設定檔要 50 次是在要一張帳單
#   - 重試時不得放寬驗證條件或換 suite
# 驗證方式:
#   - python -m pytest -q tests\test_self_heal.py
# ------------------------------------------------------------

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import server
from providers import http


FAKE_MODEL = "<fake-model-for-test>"
KEY_ENV = "DEV_TRIANGLE_TEST_ARCHITECT_KEY"
CANARY_KEY = "ghp_devTriangleCanary0000000000000000"


def roles() -> dict[str, Any]:
    return {
        "orchestrator": {"displayName": "", "kind": "mcp-client", "enabled": True},
        "contextBroker": {
            "displayName": "", "kind": "api", "provider": "", "dialect": "", "model": "",
            "baseUrl": "", "apiKeyEnv": "", "maxInputTokens": None, "enabled": False,
        },
        "architect": {
            "displayName": "架構師", "kind": "api", "provider": "test", "dialect": "openai",
            "model": FAKE_MODEL, "baseUrl": "https://architect.invalid/v1",
            "apiKeyEnv": KEY_ENV, "maxInputTokens": None, "enabled": True,
        },
        "cloudWorker": {"displayName": "", "kind": "jules", "apiKeyEnv": "JULES_API_KEY", "enabled": True},
        "verifier": {"displayName": "", "kind": "local-suite", "enabled": True},
        "diagnostician": {"displayName": "", "kind": "cli", "command": "agy", "model": "", "enabled": True},
        "reporter": {"displayName": "", "kind": "mcp", "server": "dev-triangle-report", "enabled": True},
    }


@pytest.fixture()
def heal_env(tmp_path: Path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / "providers.example.json").write_text(
        json.dumps({"schemaVersion": 1, "displayName": "", "roles": roles()}, indent=2), encoding="utf-8"
    )
    repo = tmp_path / "target-repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    manifest = repo / ".dev-triangle" / "verify.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    import sys

    manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "suites": {"default": {"commands": [[sys.executable, "-c", "import sys; sys.exit(1)"]], "timeoutSec": 60}},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    for args in (
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "test"],
        ["add", "-A"],
        ["commit", "-qm", "first"],
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    (config / "outbound-repos.json").write_text(
        json.dumps({"schemaVersion": 1, "allowedRepos": [str(repo)]}, indent=2), encoding="utf-8"
    )
    monkeypatch.setenv("DEV_TRIANGLE_CONFIG_DIR", str(config))
    monkeypatch.setenv("DEV_TRIANGLE_PROFILE", "example")
    monkeypatch.setenv(KEY_ENV, "not-a-real-key")
    if server.LEDGER_PATH.exists():
        server.LEDGER_PATH.unlink()
    yield repo
    if server.LEDGER_PATH.exists():
        server.LEDGER_PATH.unlink()


def failing_job(repo: Path, stdout_text: str = "assertion failed") -> str:
    log = server.LOG_DIR / "fake-failure.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(stdout_text, encoding="utf-8")
    job = server.new_job_skeleton(provider="dev-triangle", route="broker-architect", title="fix the failure")
    job["contextBrief"]["impactedFiles"] = ["src/main.py"]
    job["verification"] = {
        "evidenceLevel": server.EVIDENCE_MACHINE,
        "suiteName": "default",
        "commands": [["python", "-c", "import sys; sys.exit(1)"]],
        "exitCode": 1,
        "stdoutPath": str(log),
        "stderrPath": str(log),
        "durationSec": 0.1,
    }
    return server.upsert_job(job)["id"]


def fake_chat(sent: list[str], patch: str = ""):
    def _chat(binding, system, user, timeout=None):
        sent.append(user)
        return {
            "targetBaseUrl": binding.base_url,
            "targetModel": binding.model,
            "text": json.dumps({"rationale": "try again", "testPlan": [], "patch": patch}),
            "usage": {"prompt_tokens": 50, "completion_tokens": 10},
        }

    return _chat


# ---------------------------------------------------------------------------
# INV-08 / F5: the loop has a brake, and it is in the code
# ---------------------------------------------------------------------------


def test_attempts_hard_capped(heal_env: Path, monkeypatch) -> None:
    repo = heal_env
    monkeypatch.setattr(http, "chat", fake_chat([]))
    job_id = failing_job(repo)

    first = server.tool_self_heal({"repoPath": str(repo), "jobId": job_id})
    assert first["attempts"] == 1
    assert first["maxAttempts"] == server.SELF_HEAL_DEFAULT_MAX_ATTEMPTS

    second = server.tool_self_heal({"repoPath": str(repo), "jobId": job_id})
    assert second["status"] == "BLOCKED"
    assert second["attempts"] == 1, "a blocked call must not spend another attempt"
    assert second["evidencePaths"], "blocking hands back the evidence, it does not just refuse"


def test_profile_cannot_raise_the_cap_past_the_code(heal_env: Path, monkeypatch) -> None:
    repo = heal_env
    monkeypatch.setattr(http, "chat", fake_chat([]))
    job_id = failing_job(repo)
    server.upsert_job({"id": job_id, "selfHeal": {"attempts": 0, "maxAttempts": 50, "history": []}})

    result = server.tool_self_heal({"repoPath": str(repo), "jobId": job_id})
    assert result["maxAttempts"] == server.SELF_HEAL_HARD_CAP


# ---------------------------------------------------------------------------
# F3: the error log is repo-controlled text on its way out
# ---------------------------------------------------------------------------


def test_error_log_is_redacted(heal_env: Path, monkeypatch) -> None:
    repo = heal_env
    sent: list[str] = []
    monkeypatch.setattr(http, "chat", fake_chat(sent))
    job_id = failing_job(repo, stdout_text=f"connection failed using token {CANARY_KEY}\n")

    result = server.tool_self_heal({"repoPath": str(repo), "jobId": job_id})

    assert result["status"] == "OUTBOUND_BLOCKED"
    assert sent == [], "a log carrying a credential must never be sent back out"


def test_clean_error_log_is_sent(heal_env: Path, monkeypatch) -> None:
    # The other branch: without it, "never send anything" would pass the test above.
    repo = heal_env
    sent: list[str] = []
    monkeypatch.setattr(http, "chat", fake_chat(sent))
    job_id = failing_job(repo, stdout_text="AssertionError: expected 2 got 3\n")

    server.tool_self_heal({"repoPath": str(repo), "jobId": job_id})

    assert sent, "a clean failure log is exactly what self-heal is for"
    assert "AssertionError: expected 2 got 3" in sent[0]


# ---------------------------------------------------------------------------
# Cost and suite integrity
# ---------------------------------------------------------------------------


def test_cost_is_recorded_every_attempt(heal_env: Path, monkeypatch) -> None:
    repo = heal_env
    monkeypatch.setattr(http, "chat", fake_chat([]))
    job_id = failing_job(repo)

    result = server.tool_self_heal({"repoPath": str(repo), "jobId": job_id})

    assert result["cost"]["calls"] == 1
    assert result["cost"]["tokensIn"] == 50
    assert result["cost"]["tokensOut"] == 10
    stored = server.tool_job_get({"jobId": job_id})["job"]
    assert stored["cost"]["calls"] == 1


def test_suite_is_never_changed_between_attempts(heal_env: Path, monkeypatch) -> None:
    repo = heal_env
    monkeypatch.setattr(http, "chat", fake_chat([]))
    job_id = failing_job(repo)

    server.tool_self_heal({"repoPath": str(repo), "jobId": job_id, "suiteName": "default"})

    stored = server.tool_job_get({"jobId": job_id})["job"]
    history = stored["selfHeal"]["history"]
    assert history, "the attempt must be booked"
    assert stored["verification"]["suiteName"] in ("default", "")


def test_passing_job_is_left_alone(heal_env: Path, monkeypatch) -> None:
    repo = heal_env
    monkeypatch.setattr(http, "chat", fake_chat([]))
    job_id = failing_job(repo)
    server.upsert_job(
        {
            "id": job_id,
            "verification": {
                "evidenceLevel": server.EVIDENCE_MACHINE,
                "suiteName": "default",
                "commands": [["x"]],
                "exitCode": 0,
                "stdoutPath": "",
            },
        }
    )

    result = server.tool_self_heal({"repoPath": str(repo), "jobId": job_id})
    assert result["status"] == "NOTHING_TO_HEAL"

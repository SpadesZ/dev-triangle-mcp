# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 收集執行；import server 與 providers.architect / http；在 tmp_path 建真的 git repo，用 monkeypatch 換掉 http.chat，不發任何網路請求
# 檔案路徑: dev-triangle-mcp/tests/test_apply_patch.py
# 產生時間: 2026-08-19 16:20 +08:00
# 版本: v1.0
# 功能說明: 釘住落地層的兩件事——working tree 不乾淨就拒絕套 patch，以及套之前一定要記下當時的 commit。少了任一個，回退就會連使用者自己的改動一起清掉
# 模組定位: W06 的突變驗證載體，守 INV-07 與 F6。它「是」對 patch 落地與回退點的測試；它「不是」對 patch 內容品質的測試
# 主要責任:
#   1. test_refuses_dirty_worktree —— 守 INV-07、F6
#   2. test_records_pre_apply_ref —— 沒有 ref 就沒有回退點
#   3. test_architect_must_include_target_destination —— 守 INV-15(c)
#   4. test_architect_never_writes_the_working_tree —— 守 A1.3 的硬約束
# 維護提醒:
#   - dirty 檢查不得改成「只警告」。它擋的是使用者未提交的改動，那是本專案唯一不可能自己還原的東西
#   - 這裡要用真的 git repo，不得用假的 status 字串。git 的輸出格式就是被測的一部分
# 驗證方式:
#   - python -m pytest -q tests\test_apply_patch.py
# ------------------------------------------------------------

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import server
from providers import architect, http


FAKE_MODEL = "<fake-model-for-test>"
KEY_ENV = "DEV_TRIANGLE_TEST_ARCHITECT_KEY"


def roles_with_architect() -> dict[str, Any]:
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
            "displayName": "首席架構師",
            "kind": "api",
            "provider": "test",
            "dialect": "openai",
            "model": FAKE_MODEL,
            "baseUrl": "https://architect.invalid/v1",
            "apiKeyEnv": KEY_ENV,
            "maxInputTokens": None,
            "enabled": True,
        },
        "cloudWorker": {"displayName": "", "kind": "jules", "apiKeyEnv": "JULES_API_KEY", "enabled": True},
        "verifier": {"displayName": "", "kind": "local-suite", "enabled": True},
        "diagnostician": {"displayName": "", "kind": "cli", "command": "agy", "model": "", "enabled": True},
        "reporter": {"displayName": "", "kind": "mcp", "server": "dev-triangle-report", "enabled": True},
    }


PATCH = """diff --git a/src/main.py b/src/main.py
index 0000001..0000002 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1 +1,2 @@
 print('hi')
+print('bye')
"""


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture()
def architect_env(tmp_path: Path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / "providers.example.json").write_text(
        json.dumps({"schemaVersion": 1, "displayName": "", "roles": roles_with_architect()}, indent=2),
        encoding="utf-8",
    )
    repo = tmp_path / "target-repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "first")
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


def fake_chat(patch: str = PATCH):
    def _chat(binding, system, user, timeout=None):
        return {
            "targetBaseUrl": binding.base_url,
            "targetModel": binding.model,
            "text": json.dumps(
                {"rationale": "add a line", "testPlan": ["python -m pytest -q"], "patch": patch}
            ),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    return _chat


def make_job(repo: Path) -> str:
    job = server.new_job_skeleton(provider="dev-triangle", route="broker-architect", title="add a line")
    job["contextBrief"]["impactedFiles"] = ["src/main.py"]
    return server.upsert_job(job)["id"]


# ---------------------------------------------------------------------------
# A1.3: the architect produces a patch, it does not edit anything
# ---------------------------------------------------------------------------


def test_architect_never_writes_the_working_tree(architect_env: Path, monkeypatch) -> None:
    repo = architect_env
    monkeypatch.setattr(http, "chat", fake_chat())
    job_id = make_job(repo)

    result = server.tool_dispatch_architect({"repoPath": str(repo), "jobId": job_id, "shadow": False})

    assert result["status"] == "OK"
    assert result["implementation"]["patchPaths"], "the patch has to land somewhere"
    assert (repo / "src" / "main.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert server.git_status_porcelain(repo).strip() == ""


def test_architect_must_include_target_destination(architect_env: Path, monkeypatch) -> None:
    repo = architect_env
    monkeypatch.setattr(http, "chat", fake_chat())
    job_id = make_job(repo)

    result = server.tool_dispatch_architect({"repoPath": str(repo), "jobId": job_id, "shadow": False})

    assert result["dispatch"]["targetBaseUrl"] == "https://architect.invalid/v1"
    assert result["dispatch"]["targetModel"] == FAKE_MODEL
    assert result["implementation"]["targetBaseUrl"] == "https://architect.invalid/v1"
    assert result["implementation"]["targetModel"] == FAKE_MODEL
    assert "architect.invalid" in result["message"]
    stored = server.tool_job_get({"jobId": job_id})["job"]
    assert stored["implementation"]["targetModel"] == FAKE_MODEL


def test_shadow_run_is_kept_but_not_compared(architect_env: Path, monkeypatch) -> None:
    repo = architect_env
    monkeypatch.setattr(http, "chat", fake_chat())
    job_id = make_job(repo)

    result = server.tool_dispatch_architect({"repoPath": str(repo), "jobId": job_id, "shadow": True})

    shadow = result["implementation"]["shadow"]
    assert shadow["ran"] is True
    assert shadow["patchPath"], "both arms are stored"
    assert "verdict" not in shadow and "better" not in shadow


# ---------------------------------------------------------------------------
# INV-07 / F6: a dirty tree has no unambiguous rollback point
# ---------------------------------------------------------------------------


def test_refuses_dirty_worktree(architect_env: Path, monkeypatch) -> None:
    repo = architect_env
    monkeypatch.setattr(http, "chat", fake_chat())
    job_id = make_job(repo)
    server.tool_dispatch_architect({"repoPath": str(repo), "jobId": job_id, "shadow": False})

    # The user has work in progress.
    (repo / "src" / "mine.py").write_text("my own edits\n", encoding="utf-8")

    result = server.tool_apply_patch({"repoPath": str(repo), "jobId": job_id})

    assert result["status"] == "REFUSED_DIRTY_WORKTREE"
    assert "src/mine.py" in result["dirtyPaths"]
    assert (repo / "src" / "main.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert (repo / "src" / "mine.py").exists(), "the user's work must still be there"


def test_records_pre_apply_ref(architect_env: Path, monkeypatch) -> None:
    repo = architect_env
    monkeypatch.setattr(http, "chat", fake_chat())
    job_id = make_job(repo)
    server.tool_dispatch_architect({"repoPath": str(repo), "jobId": job_id, "shadow": False})
    head_before = server.git_head_sha(repo)

    result = server.tool_apply_patch({"repoPath": str(repo), "jobId": job_id})

    assert result["status"] == "APPLIED"
    assert result["appliedAtRef"] == head_before
    assert head_before in result["rollbackCommand"]
    assert "print('bye')" in (repo / "src" / "main.py").read_text(encoding="utf-8")
    stored = server.tool_job_get({"jobId": job_id})["job"]
    assert stored["implementation"]["appliedAtRef"] == head_before


def test_rollback_actually_works(architect_env: Path, monkeypatch) -> None:
    # The ref is only worth recording if it restores the file.
    repo = architect_env
    monkeypatch.setattr(http, "chat", fake_chat())
    job_id = make_job(repo)
    server.tool_dispatch_architect({"repoPath": str(repo), "jobId": job_id, "shadow": False})
    applied = server.tool_apply_patch({"repoPath": str(repo), "jobId": job_id})

    git(repo, "reset", "--hard", applied["appliedAtRef"])
    assert (repo / "src" / "main.py").read_text(encoding="utf-8") == "print('hi')\n"


def test_broken_patch_reports_instead_of_raising(architect_env: Path, monkeypatch) -> None:
    repo = architect_env
    monkeypatch.setattr(http, "chat", fake_chat(patch="this is not a diff at all\n"))
    job_id = make_job(repo)
    server.tool_dispatch_architect({"repoPath": str(repo), "jobId": job_id, "shadow": False})

    result = server.tool_apply_patch({"repoPath": str(repo), "jobId": job_id})
    assert result["status"] == "APPLY_FAILED"
    assert result["appliedAtRef"], "even a failed apply records where we were"

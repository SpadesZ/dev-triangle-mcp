# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 收集執行；import server 並對 conftest 指定的臨時 DEV_TRIANGLE_HOME 底下的 jobs.json 讀寫；不碰使用者真正的帳本
# 檔案路徑: dev-triangle-mcp/tests/test_ledger_naming.py
# 產生時間: 2026-08-19 12:35 +08:00
# 版本: v1.0
# 功能說明: 掃 jobs.json 的所有鍵，只要出現底線就失敗。提案給的 schema 是 snake_case，現有帳本是 camelCase，照抄提案會讓同一個檔案裡同時出現 job_id 與 id
# 模組定位: W02 的命名 lint，守 INV-09。它「是」對帳本鍵名的機械檢查；它「不是」對帳本內容或 schema 完整性的檢查（那是 tests/test_ledger_schema.py）
# 主要責任:
#   1. test_no_snake_case_keys —— 實際寫一筆 job 進帳本再掃整個檔案
#   2. test_lint_detects_snake_case —— 反向分支，證明掃描器不是永遠回空
#   3. test_new_job_skeleton_has_every_v2_section —— 新 job 必須四段齊全
# 維護提醒:
#   - 不得只留第 1 支。一個永遠回報「沒有底線」的掃描器也會讓它全綠（SAI I0.3）
#   - 掃描要連巢狀 dict 與 list 裡的 dict 一起掃。真正會出事的是 contextBrief 那種第二層，不是頂層
# 驗證方式:
#   - python -m pytest -q tests\test_ledger_naming.py
# ------------------------------------------------------------

from __future__ import annotations

import json
from typing import Any

import pytest

import server


def snake_case_keys(node: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if isinstance(key, str) and "_" in key:
                found.append(here)
            found.extend(snake_case_keys(value, here))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(snake_case_keys(value, f"{path}[{index}]"))
    return found


@pytest.fixture()
def clean_ledger():
    if server.LEDGER_PATH.exists():
        server.LEDGER_PATH.unlink()
    yield server.LEDGER_PATH
    if server.LEDGER_PATH.exists():
        server.LEDGER_PATH.unlink()


def test_no_snake_case_keys(clean_ledger) -> None:
    server.upsert_job(server.new_job_skeleton(provider="dev-triangle", route="local", title="naming lint"))
    ledger = json.loads(clean_ledger.read_text(encoding="utf-8"))
    assert snake_case_keys(ledger) == []


def test_lint_detects_snake_case() -> None:
    # Without this, a scanner that never reports anything would pass the test
    # above and INV-09 would be guarded by nothing.
    polluted = {"jobs": [{"id": "x", "contextBrief": {"impacted_files": []}}]}
    assert snake_case_keys(polluted) == ["jobs[0].contextBrief.impacted_files"]


def test_new_job_skeleton_has_every_v2_section() -> None:
    job = server.new_job_skeleton(provider="dev-triangle", route="broker-architect")
    for section in ("contextBrief", "implementation", "verification", "selfHeal", "cost"):
        assert isinstance(job[section], dict), f"missing section {section}"
    assert job["schemaVersion"] == server.JOB_SCHEMA_VERSION
    assert job["selfHeal"]["maxAttempts"] == server.SELF_HEAL_DEFAULT_MAX_ATTEMPTS


def test_unknown_route_is_rejected() -> None:
    with pytest.raises(server.ToolError):
        server.new_job_skeleton(provider="dev-triangle", route="whatever-i-felt-like")

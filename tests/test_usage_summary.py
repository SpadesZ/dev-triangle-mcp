# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 收集執行；import server，對 conftest 指定的臨時帳本寫 job 與 dispatch 紀錄再彙總；不啟動子行程、不發網路請求
# 檔案路徑: dev-triangle-mcp/tests/test_usage_summary.py
# 產生時間: 2026-08-19 20:10 +08:00
# 版本: v1.0
# 功能說明: 釘住用量彙總不會把「量不到」講成「沒花錢」。CLI 角色不回報 token，那一列必須標成資料不完整，而不是顯示 0
# 模組定位: W18 的突變驗證載體，守 NOTE-010。它「是」對彙總正確性的測試；它「不是」對計費金額的測試——本專案不知道任何一家的價目表，也不該假裝知道
# 主要責任:
#   1. test_cli_rows_are_marked_unmeasured —— CLI 來源的列 tokensAvailable 為 false
#   2. test_zero_is_never_used_to_mean_unmeasured —— 反向分支，防止用 0 冒充
#   3. test_one_unmeasured_call_taints_the_whole_row —— 混合來源時整列算不完整
#   4. test_api_rows_keep_real_token_totals —— API 列照常有數字，避免整支測試被「一律標不可用」矇混
#   5. test_cli_accounts_are_not_merged —— 守不同 profile／執行檔不會因空 model 被合併
#   6. test_jobs_counted_respects_since_days —— job 計數與 dispatch 時間窗使用同一個口徑
# 維護提醒:
#   - 不得為了讓報表好看而把 CLI 列的 token 填 0。那會讓最便宜的那一列剛好是沒人看得到成本的那一列
#   - 不得在此檔引入任何價目表或金額換算。本專案不知道使用者的方案與費率
# 驗證方式:
#   - python -m pytest -q tests\test_usage_summary.py
# ------------------------------------------------------------

from __future__ import annotations

import json
from typing import Any

import pytest

import server


class FakeBinding:
    def __init__(self, slot: str, kind: str, label: str = "") -> None:
        self.slot = slot
        self.kind = kind
        self.label = label or slot


def api_payload(tokens_in: int = 100, tokens_out: int = 20) -> dict[str, Any]:
    return {
        "targetBaseUrl": "https://api.invalid/v1",
        "targetModel": "<fake-model-for-test>",
        "tokensIn": tokens_in,
        "tokensOut": tokens_out,
        "tokensAvailable": True,
    }


def cli_payload(target_base_url: str = "C:/tools/claude.cmd") -> dict[str, Any]:
    return {
        "targetBaseUrl": target_base_url,
        "targetModel": "",
        "tokensIn": 0,
        "tokensOut": 0,
        "tokensAvailable": False,
    }


@pytest.fixture()
def clean_ledger():
    if server.LEDGER_PATH.exists():
        server.LEDGER_PATH.unlink()
    yield
    if server.LEDGER_PATH.exists():
        server.LEDGER_PATH.unlink()


def job_with_dispatches(*records: tuple[FakeBinding, dict[str, Any]], profile: str = "") -> str:
    job = server.upsert_job(
        server.new_job_skeleton(provider="dev-triangle", route="broker-architect", profile=profile)
    )
    for binding, payload in records:
        merged = server.merge_dispatch(job, server.dispatch_record(binding, payload))
        job = server.upsert_job({"id": job["id"], **merged})
    return job["id"]


def row_for(summary: dict[str, Any], slot: str) -> dict[str, Any]:
    return [row for row in summary["byRole"] if row["slot"] == slot][0]


# ---------------------------------------------------------------------------
# NOTE-010: unmeasured is not zero
# ---------------------------------------------------------------------------


def test_cli_rows_are_marked_unmeasured(clean_ledger) -> None:
    job_with_dispatches((FakeBinding("architect", "cli"), cli_payload()))

    summary = server.tool_usage_summary({})
    row = row_for(summary, "architect")

    assert row["calls"] == 1
    assert row["tokensAvailable"] is False
    assert "architect" in summary["rowsWithoutTokenData"]
    assert "not free" in summary["message"]


def test_zero_is_never_used_to_mean_unmeasured(clean_ledger) -> None:
    # The failure this guards against is subtle: a row showing 0 tokens next to
    # rows showing real numbers reads as "this one was cheap".
    job_with_dispatches(
        (FakeBinding("architect", "cli"), cli_payload()),
        (FakeBinding("contextBroker", "api"), api_payload()),
    )

    summary = server.tool_usage_summary({})
    cli_row = row_for(summary, "architect")
    api_row = row_for(summary, "contextBroker")

    assert cli_row["tokensAvailable"] is False
    assert api_row["tokensAvailable"] is True
    assert api_row["tokensIn"] == 100
    # The CLI row's zeroes must never be read without the flag beside them.
    assert cli_row["callsWithTokens"] == 0


def test_one_unmeasured_call_taints_the_whole_row(clean_ledger) -> None:
    # Same binding, two calls, and the provider reported usage on only one of
    # them. The row's token total is therefore partial, and saying otherwise
    # would understate spend.
    binding = FakeBinding("architect", "api")
    silent = {**api_payload(), "tokensIn": 0, "tokensOut": 0, "tokensAvailable": False}
    job_with_dispatches((binding, api_payload(100, 20)), (binding, silent))

    row = row_for(server.tool_usage_summary({}), "architect")
    assert row["calls"] == 2
    assert row["callsWithTokens"] == 1
    assert row["tokensIn"] == 100, "measured calls still contribute"
    assert row["tokensAvailable"] is False, "but the total is not the whole story"


def test_api_rows_keep_real_token_totals(clean_ledger) -> None:
    # Without this, "mark everything unavailable" would pass the tests above.
    binding = FakeBinding("contextBroker", "api")
    job_with_dispatches((binding, api_payload(100, 20)), (binding, api_payload(50, 10)))

    row = row_for(server.tool_usage_summary({}), "contextBroker")
    assert row["tokensAvailable"] is True
    assert (row["tokensIn"], row["tokensOut"]) == (150, 30)
    assert server.tool_usage_summary({})["rowsWithoutTokenData"] == []


# ---------------------------------------------------------------------------
# Aggregation basics
# ---------------------------------------------------------------------------


def test_cost_records_calls_that_could_not_be_priced(clean_ledger) -> None:
    job_id = job_with_dispatches((FakeBinding("architect", "cli"), cli_payload()))
    cost = server.tool_job_get({"jobId": job_id})["job"]["cost"]
    assert cost["calls"] == 1
    assert cost["callsWithoutTokens"] == 1
    assert cost["tokensIn"] == 0


def test_rows_are_grouped_by_slot_kind_and_model(clean_ledger) -> None:
    job_with_dispatches(
        (FakeBinding("architect", "api"), api_payload()),
        (FakeBinding("architect", "cli"), cli_payload()),
    )
    summary = server.tool_usage_summary({})
    slots = sorted((row["slot"], row["kind"]) for row in summary["byRole"])
    assert slots == [("architect", "api"), ("architect", "cli")]


def test_cli_accounts_are_not_merged(clean_ledger) -> None:
    job_with_dispatches(
        (FakeBinding("architect", "cli", "Claude CLI"), cli_payload("C:/tools/claude.exe")),
        profile="claude-heavy",
    )
    job_with_dispatches(
        (FakeBinding("architect", "cli", "Gemini CLI"), cli_payload("C:/tools/gemini.cmd")),
        profile="gemini-heavy",
    )

    summary = server.tool_usage_summary({})

    assert len(summary["byRole"]) == 2
    assert {row["profile"] for row in summary["byRole"]} == {"claude-heavy", "gemini-heavy"}
    assert {row["targetBaseUrl"] for row in summary["byRole"]} == {
        "C:/tools/claude.exe",
        "C:/tools/gemini.cmd",
    }
    assert {row["displayName"] for row in summary["byRole"]} == {"Claude CLI", "Gemini CLI"}
    assert {row["profile"] for row in summary["unmeasuredRows"]} == {
        "claude-heavy",
        "gemini-heavy",
    }


def test_profile_filter_narrows_the_rollup(clean_ledger) -> None:
    job = server.upsert_job(
        server.new_job_skeleton(provider="dev-triangle", route="local", profile="cheap")
    )
    merged = server.merge_dispatch(job, server.dispatch_record(FakeBinding("architect", "api"), api_payload()))
    server.upsert_job({"id": job["id"], **merged})

    assert server.tool_usage_summary({"profile": "cheap"})["totalCalls"] == 1
    assert server.tool_usage_summary({"profile": "careful"})["totalCalls"] == 0


def test_jobs_without_dispatches_are_not_counted(clean_ledger) -> None:
    server.upsert_job(server.new_job_skeleton(provider="dev-triangle", route="local"))
    summary = server.tool_usage_summary({})
    assert summary["jobsCounted"] == 0
    assert summary["byRole"] == []


def test_jobs_counted_respects_since_days(clean_ledger) -> None:
    job = server.upsert_job(
        server.new_job_skeleton(provider="dev-triangle", route="architect-only", profile="old")
    )
    record = server.dispatch_record(FakeBinding("architect", "cli"), cli_payload())
    record["at"] = "2000-01-01T00:00:00+00:00"
    server.upsert_job({"id": job["id"], **server.merge_dispatch(job, record)})

    summary = server.tool_usage_summary({"sinceDays": 1})

    assert summary["jobsCounted"] == 0
    assert summary["totalCalls"] == 0
    assert summary["byRole"] == []

# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 收集執行；import server，對 conftest 指定的臨時帳本寫 job 再呼叫 tool_job_update；不啟動子行程、不碰使用者真正的帳本
# 檔案路徑: dev-triangle-mcp/tests/test_quality_gate.py
# 產生時間: 2026-08-19 13:45 +08:00
# 版本: v1.0
# 功能說明: 釘住「SUCCESS 只能由機器憑據支撐」這件事。代理人自述最高只能到 NEEDS_REVIEW，而且不能拿語法檢查那種輔助 suite 的綠燈冒充完整驗證
# 模組定位: W04 的突變驗證載體，守 INV-03。它「是」對裁決規則的測試；它「不是」對憑據怎麼產生的測試（那是 tests/test_verification_suite.py）
# 主要責任:
#   1. test_agent_asserted_success_downgraded —— INV-03 第一條分支（沒有機器憑據）
#   2. test_machine_nonzero_exit_not_success —— INV-03 第二條分支（有憑據但非 0）
#   3. test_non_primary_suite_cannot_grant_success —— VUL-04（拿 quick suite 冒充）
#   4. test_machine_zero_exit_on_primary_suite_is_success —— 放行分支，避免「一律降級」矇混
# 維護提醒:
#   - 四支必須同時存在。只測其中一條分支，其餘幾條被拿掉時仍會全綠（SAI I0.3 明文）
#   - 不得把降級改成「只警告不改寫」來讓既有流程好看。上線後成功率帳面下降是預期行為，
#     那是量尺變準不是系統變壞（owner gate #5）
# 驗證方式:
#   - python -m pytest -q tests\test_quality_gate.py
# ------------------------------------------------------------

from __future__ import annotations

import pytest

import server


@pytest.fixture()
def clean_ledger():
    if server.LEDGER_PATH.exists():
        server.LEDGER_PATH.unlink()
    yield
    if server.LEDGER_PATH.exists():
        server.LEDGER_PATH.unlink()


def make_job(**verification) -> dict:
    job = server.new_job_skeleton(provider="dev-triangle", route="local", title="gate test")
    if verification:
        job["verification"].update(verification)
    return server.upsert_job(job)


def machine_evidence(exit_code: int = 0, suite: str = "default") -> dict:
    return {"evidenceLevel": server.EVIDENCE_MACHINE, "exitCode": exit_code, "suiteName": suite}


# ---------------------------------------------------------------------------
# INV-03 branch 1: no machine evidence at all
# ---------------------------------------------------------------------------


def test_agent_asserted_success_downgraded(clean_ledger) -> None:
    job = make_job(evidenceLevel=server.EVIDENCE_AGENT_ASSERTED, exitCode=0, suiteName="default")

    result = server.tool_job_update({"jobId": job["id"], "status": "SUCCESS"})

    assert result["requestedStatus"] == "SUCCESS"
    assert result["status"] == "NEEDS_REVIEW"
    assert result["qualityGate"]["downgraded"] is True
    assert "machine evidence" in result["qualityGate"]["reason"]
    assert result["job"]["status"] == "NEEDS_REVIEW"


def test_job_with_no_verification_cannot_be_success(clean_ledger) -> None:
    job = make_job()
    result = server.tool_job_update({"jobId": job["id"], "status": "SUCCESS"})
    assert result["status"] == "NEEDS_REVIEW"


# ---------------------------------------------------------------------------
# INV-03 branch 2: machine evidence, wrong exit code
# ---------------------------------------------------------------------------


def test_machine_nonzero_exit_not_success(clean_ledger) -> None:
    # Only testing branch 1 would leave this one permanently green.
    job = make_job(**machine_evidence(exit_code=1))

    result = server.tool_job_update({"jobId": job["id"], "status": "SUCCESS"})

    assert result["status"] == "NEEDS_REVIEW"
    assert "exitCode 0" in result["qualityGate"]["reason"]


# ---------------------------------------------------------------------------
# VUL-04: a quick suite is not the project passing
# ---------------------------------------------------------------------------


def test_non_primary_suite_cannot_grant_success(clean_ledger) -> None:
    job = make_job(**machine_evidence(exit_code=0, suite="quick"))

    result = server.tool_job_update({"jobId": job["id"], "status": "SUCCESS"})

    assert result["status"] == "NEEDS_REVIEW"
    assert "primary suite" in result["qualityGate"]["reason"]


# ---------------------------------------------------------------------------
# The pass branch: without it, "always downgrade" would satisfy everything above
# ---------------------------------------------------------------------------


def test_machine_zero_exit_on_primary_suite_is_success(clean_ledger) -> None:
    job = make_job(**machine_evidence(exit_code=0, suite="default"))

    result = server.tool_job_update({"jobId": job["id"], "status": "SUCCESS"})

    assert result["status"] == "SUCCESS"
    assert "qualityGate" not in result


def test_other_statuses_are_untouched(clean_ledger) -> None:
    # The gate guards one word. BLOCKED, RUNNING and friends pass through.
    job = make_job()
    result = server.tool_job_update({"jobId": job["id"], "status": "BLOCKED"})
    assert result["status"] == "BLOCKED"
    assert "qualityGate" not in result


# ---------------------------------------------------------------------------
# The agent report path keeps working, it just loses its authority
# ---------------------------------------------------------------------------


def test_agent_reports_are_labelled_agent_asserted() -> None:
    # Reading the constant rather than the string literal, so renaming it in one
    # file and not the other shows up here.
    assert server.EVIDENCE_AGENT_ASSERTED == "agent_asserted"
    assert server.EVIDENCE_MACHINE == "machine"


def test_machine_verified_rate_numerator_requires_both_conditions() -> None:
    # S4.1 counts SUCCESS jobs whose evidence is machine AND exit code 0. This
    # asserts the gate agrees with that definition rather than a looser one.
    assert server.evaluate_quality_gate({"verification": machine_evidence(0, "default")}, "SUCCESS")[0] == "SUCCESS"
    assert server.evaluate_quality_gate({"verification": machine_evidence(1, "default")}, "SUCCESS")[0] == "NEEDS_REVIEW"
    assert server.evaluate_quality_gate({"verification": {"evidenceLevel": "agent_asserted", "exitCode": 0, "suiteName": "default"}}, "SUCCESS")[0] == "NEEDS_REVIEW"

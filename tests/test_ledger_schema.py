# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 收集執行；import server 並對 conftest 指定的臨時 DEV_TRIANGLE_HOME 底下的 jobs.json 讀寫；不碰使用者真正的帳本
# 檔案路徑: dev-triangle-mcp/tests/test_ledger_schema.py
# 產生時間: 2026-08-19 12:35 +08:00
# 版本: v1.0
# 功能說明: 證明升到 schema v2 之後，舊的 v1 job 還讀得出來、筆數不變、而且不會被偷偷改寫。帳本是這個專案唯一的歷史紀錄，遷移腳本寫壞就是弄丟歷史
# 模組定位: W02 的相容性測試，守 INV-09 的 additive 規則。它「是」對讀寫相容性的測試；它「不是」對鍵名風格的檢查（那是 tests/test_ledger_naming.py）
# 主要責任:
#   1. test_v1_job_survives_load —— v1 job 讀得出來且欄位原值不變
#   2. test_v1_job_is_not_migrated_on_save —— 讀寫一輪之後檔案裡的舊 job 沒有被加上新欄位
#   3. test_upsert_preserves_concurrent_fields —— upsert_job 必須維持 dict.update 語意
#   4. test_config_changes_list_is_additive —— 舊帳本載入後多出空的 configChanges
# 維護提醒:
#   - 不得把 job_with_defaults 改成就地填充。就地填充會讓下一次 save_ledger 重寫每一筆歷史 job，那是遷移不是相容
#   - 不得把 upsert_job 的 existing.update(job) 改成整筆覆寫。並行寫入時會把別人剛寫的欄位清掉
# 驗證方式:
#   - python -m pytest -q tests\test_ledger_schema.py
# ------------------------------------------------------------

from __future__ import annotations

import json

import pytest

import server


V1_JOB = {
    "id": "job-legacy-0001",
    "provider": "jules",
    "title": "a job created before schema v2",
    "status": "SUCCESS",
    "createdAt": "2026-06-20T10:00:00+00:00",
    "updatedAt": "2026-06-20T10:30:00+00:00",
    "external": {"name": "sessions/abc", "id": "abc", "url": "https://example.invalid/abc"},
}


@pytest.fixture()
def v1_ledger():
    payload = {
        "schemaVersion": 1,
        "createdAt": "2026-06-20T09:00:00+00:00",
        "updatedAt": "2026-06-20T10:30:00+00:00",
        "jobs": [dict(V1_JOB)],
        "handoffs": [],
    }
    server.LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    server.LEDGER_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    yield server.LEDGER_PATH
    if server.LEDGER_PATH.exists():
        server.LEDGER_PATH.unlink()


def test_v1_job_survives_load(v1_ledger) -> None:
    ledger = server.load_ledger()
    assert len(ledger["jobs"]) == 1

    view = server.job_with_defaults(ledger["jobs"][0])
    # Original values untouched.
    for key, value in V1_JOB.items():
        assert view[key] == value
    # New sections readable rather than KeyError.
    assert view["schemaVersion"] == 1
    assert view["verification"]["exitCode"] is None
    assert view["contextBrief"]["impactedFiles"] == []
    assert view["selfHeal"]["attempts"] == 0
    assert view["cost"]["calls"] == 0


def test_v1_job_is_not_migrated_on_save(v1_ledger) -> None:
    # Read, touch something unrelated, write. The old job must come back out of
    # the file exactly as it went in: no new sections, no schemaVersion rewrite.
    ledger = server.load_ledger()
    server.save_ledger(ledger)

    stored = json.loads(v1_ledger.read_text(encoding="utf-8"))
    assert stored["jobs"][0] == V1_JOB
    assert stored["schemaVersion"] == 1


def test_reading_a_job_does_not_mutate_the_stored_record(v1_ledger) -> None:
    # The dangerous sequence is read -> view -> save on the same ledger object.
    # If job_with_defaults filled in place, this is where a whole ledger of
    # history would quietly gain sections it never had.
    ledger = server.load_ledger()
    stored_job = ledger["jobs"][0]

    view = server.job_with_defaults(stored_job)
    view["verification"]["exitCode"] = 0
    view["stage"] = "DONE"

    assert "verification" not in stored_job, "job_with_defaults must return a copy"
    assert "stage" not in stored_job

    server.save_ledger(ledger)
    assert json.loads(v1_ledger.read_text(encoding="utf-8"))["jobs"][0] == V1_JOB


def test_new_v2_job_raises_the_file_schema_version(v1_ledger) -> None:
    server.upsert_job(server.new_job_skeleton(provider="dev-triangle", route="local"))
    stored = json.loads(v1_ledger.read_text(encoding="utf-8"))
    assert stored["schemaVersion"] == server.JOB_SCHEMA_VERSION
    # The v1 job is still there, still v1-shaped.
    legacy = [job for job in stored["jobs"] if job["id"] == V1_JOB["id"]][0]
    assert legacy == V1_JOB
    assert len(stored["jobs"]) == 2


def test_upsert_preserves_concurrent_fields(v1_ledger) -> None:
    job = server.new_job_skeleton(provider="dev-triangle", route="local")
    server.upsert_job(job)
    server.upsert_job({"id": job["id"], "stage": "VERIFICATION"})

    stored = json.loads(v1_ledger.read_text(encoding="utf-8"))
    saved = [item for item in stored["jobs"] if item["id"] == job["id"]][0]
    assert saved["stage"] == "VERIFICATION"
    # A whole-record overwrite would have dropped these.
    assert saved["contextBrief"]["impactedFiles"] == []
    assert saved["provider"] == "dev-triangle"


def test_config_changes_list_is_additive(v1_ledger) -> None:
    ledger = server.load_ledger()
    assert ledger["configChanges"] == []

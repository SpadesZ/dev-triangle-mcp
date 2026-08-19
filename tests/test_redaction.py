# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 收集執行；import providers.redaction 與 server（為了驗證發布掃描仍走同一份規則）；在 tmp_path 下建臨時 repo，不碰使用者的任何檔案
# 檔案路徑: dev-triangle-mcp/tests/test_redaction.py
# 產生時間: 2026-08-19 11:25 +08:00
# 版本: v1.0
# 功能說明: 證明外送遮罩真的會攔到東西。SAI S4.7 的 secret_leak_count 門檻是 0，而「把掃描器寫成永遠回空清單」也是 0——本檔就是分辨這兩者的那把尺
# 模組定位: W08 的突變驗證載體，也是 S4.7 這條量尺能不能算數的唯一依據。它「是」規則層的單元測試；它「不是」對外送策略的測試（呼叫端要不要 fail-closed 由 W05/W06/W07 各自的測試守）
# 主要責任:
#   1. test_canary_secret_is_caught —— 種一個 canary 金鑰，掃描器沒攔到就紅
#   2. test_clean_payload_has_no_hits —— 反向分支，防止「永遠回報命中」矇混過關
#   3. test_home_path_masked —— 家目錄絕對路徑必須變成 <HOME>
#   4. test_hits_never_echo_the_secret —— 守 docs/NOTES.md NOTE-003
#   5. test_env_var_name_is_not_mistaken_for_a_secret / test_pasted_key_is_rejected —— apiKeyEnv 驗證器的兩條分支
#   6. test_publish_scan_still_uses_shared_rules —— 證明抽取之後 scan_repo_for_publish_safety 行為沒變
# 維護提醒:
#   - 不得只留第 1 支。只測「有秘密會紅」的話，一個永遠回報命中的掃描器也會全綠（SAI I0.3）
#   - canary 字串不得換成真的金鑰。它們是刻意造出來、對不到任何真實帳號的形狀
#   - 第 6 支若因為 SECRET_CONTENT_PATTERNS 被改動而變紅，要回頭確認 prepare_jules_repo 的行為是否被連帶改掉（W08 明文禁止）
# 驗證方式:
#   - python -m pytest -q tests\test_redaction.py
# ------------------------------------------------------------

from __future__ import annotations

import json
import os
from pathlib import Path

import server
from providers import redaction


# Shaped like the real thing, matched to no real account.
CANARY_GITHUB_PAT = "ghp_devTriangleCanary0000000000000000"
CANARY_JULES_KEY = "AQ.devTriangleCanaryValue0000000000"
CANARY_OPENAI_KEY = "sk-devTriangleCanary000000000000000000"


def test_canary_secret_is_caught() -> None:
    for canary in (CANARY_GITHUB_PAT, CANARY_JULES_KEY, CANARY_OPENAI_KEY):
        _, hits = redaction.redact_payload(f"the build failed with token {canary} in the log")
        assert hits, f"redaction missed {canary[:6]}..."


def test_clean_payload_has_no_hits() -> None:
    # Without this, a scanner that always reports a hit would pass the canary
    # test and S4.7 would be measuring nothing.
    text = "ImportError: cannot import name 'load_profile' from 'providers.profiles'"
    _, hits = redaction.redact_payload(text)
    assert hits == []


def test_home_path_masked() -> None:
    home = os.environ.get("USERPROFILE") or str(Path.home())
    text = f"traceback from {home}\\projects\\demo\\main.py line 12"
    masked, _ = redaction.redact_payload(text)
    assert redaction.HOME_PLACEHOLDER in masked
    assert home not in masked


def test_home_path_masked_with_forward_slashes() -> None:
    # Same path, different separator: JSON round-trips turn C:\Users into C:/Users.
    home = (os.environ.get("USERPROFILE") or str(Path.home())).replace("\\", "/")
    masked = redaction.mask_home_paths(f"cwd={home}/projects/demo")
    assert redaction.HOME_PLACEHOLDER in masked
    assert home not in masked


def test_hits_never_echo_the_secret() -> None:
    # NOTE(NOTE-003): hits travel into jobs.json and back into the orchestrator
    # context. A "helpful" sample field would make the detector a leak path.
    _, hits = redaction.redact_payload(f"token={CANARY_GITHUB_PAT}")
    assert hits
    serialized = json.dumps(hits)
    for start in range(0, len(CANARY_GITHUB_PAT) - 12):
        fragment = CANARY_GITHUB_PAT[start : start + 12]
        assert fragment not in serialized


def test_env_var_name_is_not_mistaken_for_a_secret() -> None:
    for name in ("MY_BROKER_API_KEY", "JULES_API_KEY", "A", "SOME_VERY_LONG_ENVIRONMENT_VARIABLE_NAME"):
        assert redaction.looks_like_secret_value(name) is None


def test_pasted_key_is_rejected() -> None:
    for canary in (CANARY_GITHUB_PAT, CANARY_JULES_KEY, CANARY_OPENAI_KEY):
        assert redaction.looks_like_secret_value(canary) is not None


def test_publish_scan_still_uses_shared_rules(tmp_path: Path) -> None:
    # The rules moved out of server.py in W08. This asserts the publish scanner
    # still reaches them, so prepare_jules_repo keeps its guard.
    assert server.SECRET_CONTENT_PATTERNS is redaction.SECRET_CONTENT_PATTERNS
    assert server.SENSITIVE_FILE_NAME_PATTERNS is redaction.SENSITIVE_FILE_NAME_PATTERNS

    repo = tmp_path / "fixture-repo"
    repo.mkdir()
    (repo / ".env").write_text("JULES_API_KEY=abcdefgh12345678\n", encoding="utf-8")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")

    report = server.scan_repo_for_publish_safety(repo)
    kinds = {finding["type"] for finding in report["blockingFindings"]}
    assert "sensitive_filename" in kinds

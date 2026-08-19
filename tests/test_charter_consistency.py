# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 收集執行；讀 server.py 的模組 docstring 與 ROADMAP.md / README.md / SECURITY.md 的禁令段落；不寫任何檔案、不啟動子行程
# 檔案路徑: dev-triangle-mcp/tests/test_charter_consistency.py
# 產生時間: 2026-08-19 11:10 +08:00
# 版本: v1.0
# 功能說明: 檢查「本專案禁止什麼」這件事在四個地方講的是同一句話。具體是釘住「禁的是 generic shell 執行器，白名單 suite runner 是具名例外」這個限定措辭，不讓它退回成無限定的全面禁令
# 模組定位: W12 的突變驗證載體，也是 W03 的合併前置。它「是」文件與程式碼一致性的機械檢查；它「不是」對執行器本身行為的測試（那是 tests/test_verification_suite.py）
# 主要責任:
#   1. test_server_charter_is_qualified —— server.py 檔頭必須是限定措辭
#   2. test_suite_runner_requires_qualified_charter —— 有執行器就必須有限定措辭（SAI W12 指名的那一支）
#   3. test_prohibition_wording_matches_across_files —— server.py / ROADMAP.md / README.md 三處措辭一致
#   4. test_security_doc_documents_attack_surface —— SECURITY.md 必須寫出惡意 verify.json 的攻擊面與 hash 閘防線
# 維護提醒:
#   - 不得把第 2 支寫成「找不到執行器就 skip」。skip 在報表上看起來是綠的，等於這條防線在 W03 落地前後都不存在
#   - 不得放寬第 1 支的斷言來讓某次改寫過關。這支測試的整個價值就在於「文件說禁止、程式碼在執行」這種無聲矛盾沒有別的東西抓得到
#   - 改寫憲章措辭時要四個檔一起改，只改一處會讓本檔變紅——那是刻意的
# 驗證方式:
#   - python -m pytest -q tests\test_charter_consistency.py
# ------------------------------------------------------------

from __future__ import annotations

from pathlib import Path

import server


def read(repo_root: Path, name: str) -> str:
    return (repo_root / name).read_text(encoding="utf-8")


def test_server_charter_is_qualified() -> None:
    # The prohibition must name what is *not* prohibited. An unqualified
    # "no shell execution" line reads as a ban on the suite runner too.
    doc = server.__doc__ or ""
    assert "generic" in doc
    assert "verify.json" in doc
    assert "callers cannot supply command strings" in doc


def test_suite_runner_requires_qualified_charter(repo_root: Path) -> None:
    # SAI W12: if the runner exists, the charter must already say so. Written as
    # an implication rather than a skip, so it stays green-for-a-reason before
    # W03 lands and gains teeth the moment it does.
    source = read(repo_root, "server.py")
    has_runner = "def tool_run_verification_suite" in source
    doc = server.__doc__ or ""
    charter_is_qualified = "generic" in doc and ("allowlist" in doc.lower() or "verify.json" in doc)
    assert charter_is_qualified or not has_runner


def test_prohibition_wording_matches_across_files(repo_root: Path) -> None:
    # Mirrors the SAI I2 command:
    #   Select-String -Path server.py,ROADMAP.md,README.md -Pattern 'generic'
    # The reading order of this repo is README -> source comments -> docs, so a
    # stale line in any one of them is what the next maintainer will follow.
    for name in ("server.py", "ROADMAP.md", "README.md", "SECURITY.md"):
        assert "generic" in read(repo_root, name), f"{name} lost the 'generic' qualifier"

    for name in ("ROADMAP.md", "README.md"):
        text = read(repo_root, name)
        assert "docs/SAI.md" in text, f"{name} must point at the approved scope"


def test_security_doc_documents_attack_surface(repo_root: Path) -> None:
    # The runner's approval was conditional on the confirmation gate existing.
    # If SECURITY.md stops describing it, the next reader has no way to know the
    # gate is load-bearing rather than an annoyance to be removed.
    text = read(repo_root, "SECURITY.md")
    assert "verify.json" in text
    assert "NEEDS_CONFIRMATION" in text
    assert "git rev-parse HEAD" in text

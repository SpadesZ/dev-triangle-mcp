# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 在收集測試前自動載入；為 tests/ 底下所有測試準備 import 路徑與隔離的狀態目錄；不被任何產品程式碼 import
# 檔案路徑: dev-triangle-mcp/tests/conftest.py
# 產生時間: 2026-08-19 10:52 +08:00
# 版本: v1.0
# 功能說明: 讓 tests/ 裡的 pytest 測試可以直接 import server 與 antigravity_report_server，並且把它們的狀態目錄(ledger、handoff、result、log)改指到一個臨時資料夾，避免測試寫壞使用者真正的 %USERPROFILE%\.dev-triangle
# 模組定位: 測試基礎設施。它「是」pytest 的環境前置；它「不是」測試案例，也「不是」產品程式碼的一部分——產品程式碼不得 import 它
# 主要責任:
#   1. 把 repo 根目錄插進 sys.path，讓 import server 成立
#   2. 在任何測試模組被 import 之前設好 DEV_TRIANGLE_HOME 與 ANTIGRAVITY_HANDOFF_DIR
#   3. 提供 repo_root fixture 給需要掃檔案的測試(例如 test_repo_integrity.py)使用
# 維護提醒:
#   - 不得把 DEV_TRIANGLE_HOME 指向 %USERPROFILE%\.dev-triangle。server.ensure_dirs() 會直接建目錄、load_ledger() 會直接寫檔，指錯地方就是拿使用者的真帳本當測試沙盒
#   - 環境變數必須在 module import 階段就設好，不能放進 fixture。server.py 是在 module 層讀 os.environ 決定路徑的，fixture 執行時已經太晚了
# 驗證方式:
#   - python -m pytest -q tests\test_antigravity_command_line.py
# ------------------------------------------------------------

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import-time, not fixture-time: server.py resolves DEV_TRIANGLE_HOME at module
# level, so anything set later would be ignored.
_TEST_STATE = Path(tempfile.mkdtemp(prefix="dev-triangle-pytest-"))
os.environ["DEV_TRIANGLE_HOME"] = str(_TEST_STATE)
os.environ["ANTIGRAVITY_HANDOFF_DIR"] = str(_TEST_STATE / "antigravity-handoffs")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def test_state_dir() -> Path:
    return _TEST_STATE

# Dev Triangle MCP source maintenance contract
# 上下游: 被 server.py 與 tests/ 以 providers.<模組> 形式 import；本身不 import 任何專案模組，也不執行任何邏輯
# 檔案路徑: dev-triangle-mcp/providers/__init__.py
# 產生時間: 2026-08-19 11:25 +08:00
# 版本: v1.0
# 功能說明: 把 providers/ 目錄變成一個 Python package，讓 from providers.redaction import ... 這種寫法成立。除此之外不做任何事
# 模組定位: package 標記檔。它「是」import 機制的必要空殼；它「不是」共用工具的放置處——不得在這裡放常數、預設值或 re-export，那會讓 import providers 產生副作用
# 主要責任:
#   1. 宣告 providers 為 package
# 維護提醒:
#   - 不得在此檔設定任何預設模型、預設 provider 或環境變數 fallback。INV-12 規定設定解析鏈的末端是報錯不是預設值，而這裡是最容易被偷偷塞進一行 or "..." 的地方
#   - 不得在此 import 子模組。providers.redaction 會被 server.py 在啟動路徑上 import，多餘的連鎖 import 會拖慢 MCP 冷啟動
# 驗證方式:
#   - python -c "import providers; print(providers.__name__)"
# ------------------------------------------------------------

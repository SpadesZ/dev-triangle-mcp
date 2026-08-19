<#
.SYNOPSIS
Compatibility wrapper for the main protocol smoke test.

.DESCRIPTION
Kept for users who remember the original script name. New local installs should
prefer scripts/smoke.ps1 because it also checks the report server and agy
detection.
#>

# Dev Triangle MCP source maintenance contract
# 上下游: 由記得舊腳本名稱的使用者執行；轉呼叫 tests/protocol_smoke.py；不寫任何設定
# 檔案路徑: dev-triangle-mcp/scripts/run-smoke.ps1
# 產生時間: 2026-08-19 17:35 +08:00
# 版本: v1.1
# 功能說明: 舊名稱的相容包裝，只跑主伺服器的 protocol smoke
# 模組定位: 相容層。它「是」保留給既有使用者的別名；它「不是」完整體檢——完整版是 scripts/smoke.ps1，那支還會檢查回報伺服器與 agy 偵測
# 主要責任:
#   1. 解析直譯器並執行 tests/protocol_smoke.py，且明確檢查 $LASTEXITCODE
# 維護提醒:
#   - 不得在本檔新增功能。新的檢查一律加進 scripts/smoke.ps1，否則兩支會各自漂移
#   - 不得刪除本檔。docs/PROVIDERS.md 的相容包裝規則要求既有入口名稱保留
# 驗證方式:
#   - .\scripts\run-smoke.ps1
# ------------------------------------------------------------

$ErrorActionPreference = "Stop"

function Invoke-Native {
  # Keep native command failures visible to callers and CI.
  param([string]$FilePath, [string[]]$Arguments)
  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
  }
}

$Root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$Python = if ($env:DEV_TRIANGLE_PYTHON -and (Test-Path -LiteralPath $env:DEV_TRIANGLE_PYTHON)) {
  $env:DEV_TRIANGLE_PYTHON
} else {
  $codexPython = Join-Path $HOME ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (Test-Path -LiteralPath $codexPython) { $codexPython } else { "python" }
}

Invoke-Native -FilePath $Python -Arguments @((Join-Path $Root "tests\protocol_smoke.py"))

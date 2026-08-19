<#
.SYNOPSIS
Runs local smoke tests for the installed Dev Triangle MCP.

.DESCRIPTION
This script compiles the Python servers, runs the deterministic main MCP smoke
test, then calls both the report server health tool and Antigravity CLI
detection through real MCP stdio processes.
#>

# Dev Triangle MCP source maintenance contract
# 上下游: 由維護者或 CI 手動執行；啟動 server.py 與 antigravity_report_server.py 兩個真的 stdio 行程；預設把狀態寫進 $HOME\.dev-triangle，可用 -StateRoot 改到別處
# 檔案路徑: dev-triangle-mcp/scripts/smoke.ps1
# 產生時間: 2026-08-19 17:35 +08:00
# 版本: v1.1
# 功能說明: 對「已安裝」的這一份做一次完整體檢——編譯兩支伺服器、跑 protocol smoke、再用真的 MCP 對話打一次回報伺服器的健康檢查與 agy 偵測
# 模組定位: 安裝後的煙霧測試。它「是」對本機這一份的驗證；它「不是」單元測試，也「不是」憑據來源——它的結果不得用來支撐 SUCCESS
# 主要責任:
#   1. Invoke-Native 明確檢查 $LASTEXITCODE，避免失敗的 Python 測試被當成通過
#   2. py_compile 兩支伺服器
#   3. 跑 tests/protocol_smoke.py
#   4. 用真的 stdio 對話取得 report health 與 antigravity_detect_cli 的回應
# 維護提醒:
#   - 不得移除 Invoke-Native 的 $LASTEXITCODE 檢查。PowerShell 不會為原生指令自動丟例外，少了它整支腳本會在測試失敗時照樣印出 pass
#   - 預設 StateRoot 是使用者真正的狀態目錄。自動化情境請務必用 -StateRoot 指到臨時目錄
# 驗證方式:
#   - .\scripts\smoke.ps1 -StateRoot $env:TEMP\dt-smoke
# ------------------------------------------------------------

param(
  [string]$ToolRoot = (Split-Path -Parent (Split-Path -Parent $PSCommandPath)),
  [string]$StateRoot = (Join-Path $HOME ".dev-triangle")
)

$ErrorActionPreference = "Stop"

function Invoke-Native {
  # PowerShell does not throw automatically for native command failures. Check
  # LASTEXITCODE explicitly so a failing Python smoke test cannot be reported as
  # a pass.
  param([string]$FilePath, [string[]]$Arguments)
  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
  }
}

$ToolRoot = [System.IO.Path]::GetFullPath($ToolRoot)
$StateRoot = [System.IO.Path]::GetFullPath($StateRoot)
$Python = if ($env:DEV_TRIANGLE_PYTHON -and (Test-Path -LiteralPath $env:DEV_TRIANGLE_PYTHON)) {
  $env:DEV_TRIANGLE_PYTHON
} else {
  $codexPython = Join-Path $HOME ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (Test-Path -LiteralPath $codexPython) { $codexPython } else { "python" }
}

$env:DEV_TRIANGLE_HOME = $StateRoot
$env:ANTIGRAVITY_HANDOFF_DIR = Join-Path $StateRoot "antigravity-handoffs"

Invoke-Native -FilePath $Python -Arguments @("-m", "py_compile", (Join-Path $ToolRoot "server.py"), (Join-Path $ToolRoot "antigravity_report_server.py"))
Invoke-Native -FilePath $Python -Arguments @((Join-Path $ToolRoot "tests\protocol_smoke.py"))

$reportHealth = @'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"dev_triangle_report_health","arguments":{}}}
'@ | & $Python (Join-Path $ToolRoot "antigravity_report_server.py")

$detect = @'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"antigravity_detect_cli","arguments":{}}}
'@ | & $Python (Join-Path $ToolRoot "server.py")

[pscustomobject]@{
  status = "pass"
  toolRoot = $ToolRoot
  stateRoot = $StateRoot
  reportHealthTail = ($reportHealth | Select-Object -Last 1)
  detectTail = ($detect | Select-Object -Last 1)
} | ConvertTo-Json -Depth 6

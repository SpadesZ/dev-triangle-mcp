<#
.SYNOPSIS
Checks whether the local Dev Triangle MCP install is healthy.

.DESCRIPTION
The doctor verifies file locations, Python, agy, Codex config, and
Antigravity/Gemini MCP config. It is intentionally read-only so it can be run
before and after install changes.
#>

# Dev Triangle MCP source maintenance contract
# 上下游: 由維護者手動執行；讀 ~/.codex/config.toml、~/.gemini/config/mcp_config.json 與 Antigravity IDE 的 mcp.json，並探測 python 與 agy；全程唯讀，不改任何設定
# 檔案路徑: dev-triangle-mcp/scripts/doctor.ps1
# 產生時間: 2026-08-19 17:35 +08:00
# 版本: v1.1
# 功能說明: 回答「我這台機器上的安裝是不是好的」。逐項檢查檔案位置、直譯器、agy、以及三份客戶端設定，任一項不通過就以 exit 1 收場
# 模組定位: 安裝健康檢查，同時是 S4.5 worker_control_plane_exposure 這條量尺的量法。它「是」唯讀的診斷；它「不是」安裝器(那是 install-local.ps1)，也「不是」煙霧測試(那是 smoke.ps1)
# 主要責任:
#   1. 檢查 toolRoot / stateRoot / 兩支伺服器檔案存在
#   2. 探測 python 與 agy 版本
#   3. orchestratorConfigured —— 至少一個 orchestrator 客戶端（Codex 或 Claude 各處設定）指向這一份 server.py
#   4. geminiOnlyReportServer / ideOnlyReportServer —— worker 端只能看到 dev-triangle-report
# 維護提醒:
#   - 第 3 項不得改回只認 Codex。docs/ROLE_MODEL.md 宣稱 orchestrator 可換，寫死一家會讓「換掉 Codex」變成假紅燈，而那種矛盾沒有任何測試抓得到（與 W12 同一類問題）
#   - 第 4 項是 INV-02 的量法，不得放寬成「包含 dev-triangle-report 就算過」。它同時要求「不含 dev-triangle」，少了後半段這條量尺就永遠是綠的
#   - 本腳本必須維持唯讀。它會在安裝前後各跑一次，有副作用就無法比較
#   - orchestratorConfigured 變紅最常見的原因不是設定壞掉，而是客戶端指向另一份 checkout
# 驗證方式:
#   - .\scripts\doctor.ps1
# ------------------------------------------------------------

param(
  [string]$ToolRoot = (Split-Path -Parent (Split-Path -Parent $PSCommandPath)),
  [string]$StateRoot = (Join-Path $HOME ".dev-triangle"),
  [switch]$Json
)

$ErrorActionPreference = "Stop"

function Test-JsonConfig {
  param([string]$Path)
  try {
    if (-not (Test-Path -LiteralPath $Path)) {
      return @{ ok = $false; message = "missing" }
    }
    $null = Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    return @{ ok = $true; message = "valid" }
  } catch {
    return @{ ok = $false; message = $_.Exception.Message }
  }
}

function Run-Command {
  # Run native commands through Start-Process so stdout/stderr can be captured
  # consistently even when a tool writes version information to stderr.
  param([string]$FilePath, [string[]]$Arguments)
  try {
    $outPath = Join-Path $env:TEMP ("dev-triangle-doctor-out-" + [guid]::NewGuid().ToString("N") + ".txt")
    $errPath = Join-Path $env:TEMP ("dev-triangle-doctor-err-" + [guid]::NewGuid().ToString("N") + ".txt")
    $proc = Start-Process -FilePath $FilePath -ArgumentList $Arguments -NoNewWindow -Wait -PassThru -RedirectStandardOutput $outPath -RedirectStandardError $errPath
    $stdoutRaw = if (Test-Path -LiteralPath $outPath) { Get-Content -Raw -LiteralPath $outPath } else { "" }
    $stderrRaw = if (Test-Path -LiteralPath $errPath) { Get-Content -Raw -LiteralPath $errPath } else { "" }
    if ($null -eq $stdoutRaw) { $stdoutRaw = "" }
    if ($null -eq $stderrRaw) { $stderrRaw = "" }
    return @{
      ok = $proc.ExitCode -eq 0
      exitCode = $proc.ExitCode
      stdout = $stdoutRaw.Trim()
      stderr = $stderrRaw.Trim()
    }
  } catch {
    return @{ ok = $false; exitCode = $null; stdout = ""; stderr = $_.Exception.Message }
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
$Agy = if ($env:ANTIGRAVITY_COMMAND -and (Test-Path -LiteralPath $env:ANTIGRAVITY_COMMAND)) {
  $env:ANTIGRAVITY_COMMAND
} else {
  $localAgy = Join-Path $env:LOCALAPPDATA "agy\bin\agy.exe"
  if (Test-Path -LiteralPath $localAgy) { $localAgy } else { "agy" }
}

$CodexConfig = Join-Path $HOME ".codex\config.toml"
$GeminiConfig = Join-Path $HOME ".gemini\config\mcp_config.json"
$IdeConfig = Join-Path $env:APPDATA "Antigravity IDE\User\mcp.json"

# Any of these may be the orchestrator. The role model says the orchestrator is
# replaceable, so this check asks "is at least one client pointed at this
# checkout", not "is Codex pointed at it".
$OrchestratorConfigs = [ordered]@{
  codex             = $CodexConfig
  claudeCodeUser    = Join-Path $HOME ".claude.json"
  claudeCodeProject = Join-Path $ToolRoot ".mcp.json"
  claudeSettings    = Join-Path $HOME ".claude\settings.json"
  claudeDesktop     = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
}

function Get-OrchestratorsPointingHere {
  param([string]$ServerPath, [System.Collections.Specialized.OrderedDictionary]$Configs)
  $found = @()
  foreach ($name in $Configs.Keys) {
    $path = $Configs[$name]
    if (-not (Test-Path -LiteralPath $path)) { continue }
    try {
      $content = Get-Content -Raw -LiteralPath $path -ErrorAction Stop
    } catch {
      continue
    }
    # Compare on the resolved server.py path. JSON escapes backslashes, so try
    # both spellings rather than parsing four different config schemas.
    $escaped = $ServerPath.Replace('\', '\\')
    if ($content -match [regex]::Escape($ServerPath) -or $content -match [regex]::Escape($escaped)) {
      $found += $name
    }
  }
  return $found
}

$checks = [ordered]@{
  toolRoot = @{ ok = (Test-Path -LiteralPath $ToolRoot); value = $ToolRoot }
  stateRoot = @{ ok = (Test-Path -LiteralPath $StateRoot); value = $StateRoot }
  server = @{ ok = (Test-Path -LiteralPath (Join-Path $ToolRoot "server.py")); value = (Join-Path $ToolRoot "server.py") }
  reportServer = @{ ok = (Test-Path -LiteralPath (Join-Path $ToolRoot "antigravity_report_server.py")); value = (Join-Path $ToolRoot "antigravity_report_server.py") }
  python = Run-Command -FilePath $Python -Arguments @("--version")
  agy = Run-Command -FilePath $Agy -Arguments @("--version")
  orchestratorConfigured = @{ ok = $false; value = "" }
  geminiConfig = Test-JsonConfig -Path $GeminiConfig
  antigravityIdeConfig = Test-JsonConfig -Path $IdeConfig
}

$orchestrators = Get-OrchestratorsPointingHere -ServerPath (Join-Path $ToolRoot "server.py") -Configs $OrchestratorConfigs
$checks.orchestratorConfigured = @{
  ok = ($orchestrators.Count -gt 0)
  value = if ($orchestrators.Count -gt 0) { $orchestrators -join ", " } else { "none of: " + (($OrchestratorConfigs.Keys) -join ", ") }
}

$gemini = if (Test-Path -LiteralPath $GeminiConfig) { Get-Content -Raw -LiteralPath $GeminiConfig | ConvertFrom-Json } else { $null }
$ide = if (Test-Path -LiteralPath $IdeConfig) { Get-Content -Raw -LiteralPath $IdeConfig | ConvertFrom-Json } else { $null }
$checks.geminiOnlyReportServer = @{
  ok = ($null -ne $gemini -and $gemini.mcpServers.PSObject.Properties.Name -contains "dev-triangle-report" -and -not ($gemini.mcpServers.PSObject.Properties.Name -contains "dev-triangle"))
  value = if ($null -ne $gemini) { $gemini.mcpServers.PSObject.Properties.Name -join ", " } else { "" }
}
$checks.ideOnlyReportServer = @{
  ok = ($null -ne $ide -and $ide.servers.PSObject.Properties.Name -contains "dev-triangle-report" -and -not ($ide.servers.PSObject.Properties.Name -contains "dev-triangle"))
  value = if ($null -ne $ide) { $ide.servers.PSObject.Properties.Name -join ", " } else { "" }
}

$allOk = -not (@($checks.Values) | Where-Object { -not $_.ok })
$result = [pscustomobject]@{
  status = if ($allOk) { "pass" } else { "fail" }
  checks = $checks
}

if ($Json) {
  $result | ConvertTo-Json -Depth 8
} else {
  "Dev Triangle MCP doctor: $($result.status)"
  foreach ($name in $checks.Keys) {
    $check = $checks[$name]
    $mark = if ($check.ok) { "PASS" } else { "FAIL" }
    $detail = if ($check.value) { $check.value } elseif ($check.stdout) { $check.stdout } elseif ($check.message) { $check.message } elseif ($check.stderr) { $check.stderr } else { "" }
    "$mark $name $detail"
  }
  if (-not $allOk) { exit 1 }
}

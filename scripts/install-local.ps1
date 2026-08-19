<#
.SYNOPSIS
Installs or refreshes Dev Triangle MCP on a local Windows machine.

.DESCRIPTION
This script writes the local MCP configuration needed by Codex and
Antigravity/Gemini. It keeps the full control-plane server attached to Codex and
the tiny report-only server attached to Antigravity. Existing config files are
backed up before modification.

Human note:
  The installer intentionally does not store JULES_API_KEY. Secrets should be
  provided through the shell environment or a real secret manager.
#>

# Dev Triangle MCP source maintenance contract
# 上下游: 由使用者手動執行；改寫 ~/.codex/config.toml、~/.gemini/config/mcp_config.json 與 Antigravity IDE 的 mcp.json；建立 $HOME\.dev-triangle 底下的狀態目錄。改任何檔案前都先備份
# 檔案路徑: dev-triangle-mcp/scripts/install-local.ps1
# 產生時間: 2026-08-19 17:35 +08:00
# 版本: v1.1
# 功能說明: 把這一份 checkout 掛到本機的客戶端上。Orchestrator（Codex 或 Claude）拿到完整控制面，Antigravity 與 Gemini 只拿到回報伺服器
# 模組定位: 安裝器。它「是」設定的寫入者；它「不是」檔案複製器——它只把路徑指向 -ToolRoot，程式碼留在原地，所以換 checkout 只要重跑一次並指定新的 ToolRoot
# 主要責任:
#   1. 解析 python 與 agy 路徑(優先用 Codex 內建的 python)
#   2. Backup-File 先備份每一份要改的設定
#   3. Set-CodexDevTriangleBlock 只替換 dev_triangle 區塊，保留使用者其他 MCP 伺服器
#   4. Upsert-ClaudeDesktopConfig 為 Claude Desktop 寫入完整控制面（-Orchestrator claude|both 時）
#   5. Upsert-GeminiConfig / Upsert-IdeConfig 主動移除 worker 端的 dev-triangle 完整控制面
# 維護提醒:
#   - 不得把 JULES_API_KEY 或任何金鑰值寫進設定檔。這裡只列環境變數「名稱」讓 Codex 繼承(INV-04)
#   - 第 5 項的 Remove-JsonPropertyIfPresent 不得省略。舊版安裝可能把完整控制面掛到 worker 端，不主動移除就會一直留著(INV-02)
#   - 不得改寫 ~/.claude.json。那是 Claude Code 自己擁有並持續重寫的大檔（含專案歷史），而且它有支援的 CLI 指令可用——本腳本改為印出那道指令，不動檔案
#   - 完整控制面只給 orchestrator。worker 端（Gemini CLI、Antigravity IDE）永遠只拿 dev-triangle-report，這條不因為換 orchestrator 而放寬
#   - 本腳本不複製檔案。ToolRoot 指到哪裡，客戶端就載入哪裡的 server.py——換 checkout 時這是唯一要動的東西
# 驗證方式:
#   - .\scripts\install-local.ps1 -ToolRoot D:\dev-triangle-mcp
#   - .\scripts\doctor.ps1
# ------------------------------------------------------------

param(
  [string]$ToolRoot = (Split-Path -Parent (Split-Path -Parent $PSCommandPath)),
  [string]$StateRoot = (Join-Path $HOME ".dev-triangle"),
  [string]$PythonPath = "",
  [string]$AgyPath = "",
  [ValidateSet("codex", "claude", "both")]
  [string]$Orchestrator = "both"
)

$ErrorActionPreference = "Stop"

function Resolve-PythonPath {
  # Prefer Codex's bundled Python when present because it makes the install less
  # dependent on the user's system Python PATH.
  param([string]$Requested)
  if ($Requested) { return $Requested }
  if ($env:DEV_TRIANGLE_PYTHON -and (Test-Path -LiteralPath $env:DEV_TRIANGLE_PYTHON)) {
    return $env:DEV_TRIANGLE_PYTHON
  }
  $codexPython = Join-Path $HOME ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (Test-Path -LiteralPath $codexPython) {
    return $codexPython
  }
  return "python"
}

function Resolve-AgyPath {
  # agy is the stable unattended Antigravity path. Falling back to "agy" lets a
  # user rely on PATH if they installed it in a custom location.
  param([string]$Requested)
  if ($Requested) { return $Requested }
  if ($env:ANTIGRAVITY_COMMAND -and (Test-Path -LiteralPath $env:ANTIGRAVITY_COMMAND)) {
    return $env:ANTIGRAVITY_COMMAND
  }
  $localAgy = Join-Path $env:LOCALAPPDATA "agy\bin\agy.exe"
  if (Test-Path -LiteralPath $localAgy) {
    return $localAgy
  }
  return "agy"
}

function Backup-File {
  param([string]$Path)
  if (Test-Path -LiteralPath $Path) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = "$Path.dev-triangle-backup-$stamp"
    Copy-Item -LiteralPath $Path -Destination $backup -Force
    return $backup
  }
  return $null
}

function Set-CodexDevTriangleBlock {
  param(
    [string]$ConfigPath,
    [string]$Block
  )
  $content = ""
  if (Test-Path -LiteralPath $ConfigPath) {
    $content = Get-Content -Raw -LiteralPath $ConfigPath
  }
  $lines = if ($content) { @($content -split "`r?`n") } else { @() }
  $out = New-Object System.Collections.Generic.List[string]
  $skip = $false

  # NOTE: This removes only the existing dev_triangle block and its env block.
  # Other MCP servers in the user's Codex config are preserved as-is.
  foreach ($line in $lines) {
    if ($line -eq "[mcp_servers.dev_triangle]") {
      $skip = $true
      continue
    }
    if ($skip -and $line -match "^\[" -and $line -notmatch "^\[mcp_servers\.dev_triangle(\.env)?\]$") {
      $skip = $false
    }
    if (-not $skip) {
      $out.Add($line)
    }
  }

  while ($out.Count -gt 0 -and [string]::IsNullOrWhiteSpace($out[$out.Count - 1])) {
    $out.RemoveAt($out.Count - 1)
  }

  $newContent = (($out -join "`r`n").TrimEnd() + "`r`n`r`n" + $Block.TrimEnd() + "`r`n")
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ConfigPath) | Out-Null
  Set-Content -LiteralPath $ConfigPath -Value $newContent -Encoding UTF8
}

function Read-JsonObject {
  param([string]$Path, [string]$RootProperty)
  if (Test-Path -LiteralPath $Path) {
    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
  }
  $obj = [pscustomobject]@{}
  $obj | Add-Member -MemberType NoteProperty -Name $RootProperty -Value ([pscustomobject]@{})
  return $obj
}

function Set-JsonProperty {
  param([object]$Object, [string]$Name, [object]$Value)
  if ($Object.PSObject.Properties.Name -contains $Name) {
    $Object.$Name = $Value
  } else {
    $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value
  }
}

function Remove-JsonPropertyIfPresent {
  param([object]$Object, [string]$Name)
  if ($Object.PSObject.Properties.Name -contains $Name) {
    $Object.PSObject.Properties.Remove($Name)
  }
}

function Write-JsonFile {
  param([string]$Path, [object]$Object)
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
  $Object | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Upsert-GeminiConfig {
  param([string]$Path, [object]$ServerConfig)
  $json = Read-JsonObject -Path $Path -RootProperty "mcpServers"
  if (-not ($json.PSObject.Properties.Name -contains "mcpServers") -or $null -eq $json.mcpServers) {
    Set-JsonProperty -Object $json -Name "mcpServers" -Value ([pscustomobject]@{})
  }
  # Antigravity should only see the report surface. If an earlier install added
  # the full dev-triangle server, remove it here to keep the worker role narrow.
  Remove-JsonPropertyIfPresent -Object $json.mcpServers -Name "dev-triangle"
  Set-JsonProperty -Object $json.mcpServers -Name "dev-triangle-report" -Value $ServerConfig
  Write-JsonFile -Path $Path -Object $json
}

function Upsert-IdeConfig {
  param([string]$Path, [object]$ServerConfig)
  $json = Read-JsonObject -Path $Path -RootProperty "servers"
  if (-not ($json.PSObject.Properties.Name -contains "servers") -or $null -eq $json.servers) {
    Set-JsonProperty -Object $json -Name "servers" -Value ([pscustomobject]@{})
  }
  # Same split as Gemini CLI config: IDE-side Antigravity gets reporting tools,
  # not the full orchestrator control plane.
  Remove-JsonPropertyIfPresent -Object $json.servers -Name "dev-triangle"
  Set-JsonProperty -Object $json.servers -Name "dev-triangle-report" -Value $ServerConfig
  Write-JsonFile -Path $Path -Object $json
}

$ToolRoot = [System.IO.Path]::GetFullPath($ToolRoot)
$StateRoot = [System.IO.Path]::GetFullPath($StateRoot)
$PythonPath = Resolve-PythonPath -Requested $PythonPath
$AgyPath = Resolve-AgyPath -Requested $AgyPath
$ServerPath = Join-Path $ToolRoot "server.py"
$ReportServerPath = Join-Path $ToolRoot "antigravity_report_server.py"
$HandoffRoot = Join-Path $StateRoot "antigravity-handoffs"

if (-not (Test-Path -LiteralPath $ServerPath)) {
  throw "server.py not found: $ServerPath"
}
if (-not (Test-Path -LiteralPath $ReportServerPath)) {
  throw "antigravity_report_server.py not found: $ReportServerPath"
}
if ($PythonPath -ne "python" -and -not (Test-Path -LiteralPath $PythonPath)) {
  throw "Python runtime not found: $PythonPath"
}

New-Item -ItemType Directory -Force -Path $StateRoot, $HandoffRoot, (Join-Path $StateRoot "antigravity-results"), (Join-Path $StateRoot "patches") | Out-Null

$CodexConfig = Join-Path $HOME ".codex\config.toml"
$GeminiConfig = Join-Path $HOME ".gemini\config\mcp_config.json"
$IdeConfig = Join-Path $env:APPDATA "Antigravity IDE\User\mcp.json"

$codexBlock = @"
[mcp_servers.dev_triangle]
command = '$PythonPath'
args = ['$ServerPath']
startup_timeout_sec = 10
tool_timeout_sec = 300
default_tools_approval_mode = "prompt"
env_vars = [
  "JULES_API_KEY",
  "JULES_BASE_URL",
  "ANTIGRAVITY_COMMAND",
  "ANTIGRAVITY_EXECUTION_STYLE",
  "ANTIGRAVITY_CHAT_MODE",
  "ANTIGRAVITY_WINDOW_MODE",
  "ANTIGRAVITY_AGY_MODEL",
  "ANTIGRAVITY_AGY_PRINT_TIMEOUT",
  "ANTIGRAVITY_AGY_SKIP_PERMISSIONS",
]

[mcp_servers.dev_triangle.env]
DEV_TRIANGLE_HOME = '$StateRoot'
ANTIGRAVITY_HANDOFF_DIR = '$HandoffRoot'
ANTIGRAVITY_COMMAND = '$AgyPath'
ANTIGRAVITY_EXECUTION_STYLE = "auto"
ANTIGRAVITY_CHAT_MODE = "agent"
ANTIGRAVITY_WINDOW_MODE = "new"
ANTIGRAVITY_AGY_PRINT_TIMEOUT = "30m"
"@

$reportServerForGemini = [pscustomobject]@{
  command = $PythonPath
  args = @($ReportServerPath)
  env = [pscustomobject]@{
    DEV_TRIANGLE_HOME = $StateRoot
    ANTIGRAVITY_HANDOFF_DIR = $HandoffRoot
  }
}

$reportServerForIde = [pscustomobject]@{
  type = "stdio"
  command = $PythonPath
  args = @($ReportServerPath)
  env = [pscustomobject]@{
    DEV_TRIANGLE_HOME = $StateRoot
    ANTIGRAVITY_HANDOFF_DIR = $HandoffRoot
  }
}

$ClaudeDesktopConfig = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"

$devTriangleForClaude = [pscustomobject]@{
  command = $PythonPath
  args = @($ServerPath)
  env = [pscustomobject]@{
    DEV_TRIANGLE_HOME = $StateRoot
    ANTIGRAVITY_HANDOFF_DIR = $HandoffRoot
    ANTIGRAVITY_COMMAND = $AgyPath
  }
}

function Upsert-ClaudeMcpConfig {
  # Same mcpServers shape as the Gemini CLI config. Unlike the worker-side
  # configs, this one gets the FULL control plane, because Claude here is
  # acting as the orchestrator, not as a worker.
  param([string]$Path, [object]$ServerConfig)
  $json = Read-JsonObject -Path $Path -RootProperty "mcpServers"
  if (-not ($json.PSObject.Properties.Name -contains "mcpServers") -or $null -eq $json.mcpServers) {
    Set-JsonProperty -Object $json -Name "mcpServers" -Value ([pscustomobject]@{})
  }
  Set-JsonProperty -Object $json.mcpServers -Name "dev-triangle" -Value $ServerConfig
  Write-JsonFile -Path $Path -Object $json
}

$backups = @()
$installedFor = @()
$notes = @()

if ($Orchestrator -in @("codex", "both")) {
  $backups += Backup-File -Path $CodexConfig
  Set-CodexDevTriangleBlock -ConfigPath $CodexConfig -Block $codexBlock
  $installedFor += "codex"
}

if ($Orchestrator -in @("claude", "both")) {
  # NOTE(NOTE-014): claude_desktop_config.json is NOT written here. The app
  # rewrites that file from its own state and drops anything we add, which
  # produces a doctor check that passes at install time and goes red hours
  # later on its own. .mcp.json is a file nothing else owns.
  # Claude Code keeps user-scope MCP servers in ~/.claude.json, a large file it
  # owns and rewrites itself. Rewriting it from here risks clobbering project
  # history for no good reason when a supported command exists - so print the
  # command instead of editing the file.
  #
  # The -e flags are not optional. Without DEV_TRIANGLE_HOME the server falls
  # back to <ToolRoot>\.dev-triangle, so Claude Code would keep a second, empty
  # ledger while Codex and Claude Desktop share the real one - two orchestrators
  # writing separate books, with no error to notice.
  # Project scope: a small file this installer owns outright, so there is no
  # race with Claude Code rewriting its own ~/.claude.json while it is running.
  $ProjectMcpConfig = Join-Path $ToolRoot ".mcp.json"
  $backups += Backup-File -Path $ProjectMcpConfig
  Upsert-ClaudeMcpConfig -Path $ProjectMcpConfig -ServerConfig $devTriangleForClaude
  $installedFor += "claude-code-project"

  $claudeCodeCommand = "claude mcp add dev-triangle --scope user" +
    " -e DEV_TRIANGLE_HOME=`"$StateRoot`"" +
    " -e ANTIGRAVITY_HANDOFF_DIR=`"$HandoffRoot`"" +
    " -e ANTIGRAVITY_COMMAND=`"$AgyPath`"" +
    " -- `"$PythonPath`" `"$ServerPath`""
  $notes += "Claude Code, this project: wrote $ProjectMcpConfig. Open Claude Code in $ToolRoot and approve the server when prompted."
  $notes += "Claude Code, every project (optional): $claudeCodeCommand"
  $notes += "No claude CLI on PATH? Add the same mcpServers entry to ~/.claude.json by hand - the shape is identical to $ProjectMcpConfig. Close Claude Code first: it rewrites that file itself and would drop the change."
  $notes += "The env block is not optional: without DEV_TRIANGLE_HOME, Claude Code keeps its own empty ledger at $ToolRoot\.dev-triangle instead of sharing $StateRoot."
  $notes += "Not written: $ClaudeDesktopConfig. That file is rewritten by the app from its own state, so an entry added here disappears within hours - see docs/NOTES.md NOTE-014."
}

# Worker-side config is written regardless of who orchestrates: these two get
# the report-only surface, and any full control plane left by an older install
# is actively removed (INV-02).
$backups += Backup-File -Path $GeminiConfig
$backups += Backup-File -Path $IdeConfig
Upsert-GeminiConfig -Path $GeminiConfig -ServerConfig $reportServerForGemini
Upsert-IdeConfig -Path $IdeConfig -ServerConfig $reportServerForIde

$result = [pscustomobject]@{
  status = "installed"
  name = "Dev Triangle MCP"
  toolRoot = $ToolRoot
  stateRoot = $StateRoot
  orchestrator = $Orchestrator
  installedFor = $installedFor
  codexConfig = $CodexConfig
  claudeDesktopConfig = $ClaudeDesktopConfig
  geminiConfig = $GeminiConfig
  antigravityIdeConfig = $IdeConfig
  backups = @($backups | Where-Object { $_ })
  notes = $notes
  agy = if (Test-Path -LiteralPath $AgyPath) { $AgyPath } else { "not-found: $AgyPath" }
}

$result | ConvertTo-Json -Depth 5

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

param(
  [string]$ToolRoot = (Split-Path -Parent (Split-Path -Parent $PSCommandPath)),
  [string]$StateRoot = (Join-Path $HOME ".dev-triangle"),
  [string]$PythonPath = "",
  [string]$AgyPath = ""
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
ANTIGRAVITY_AGY_MODEL = "Gemini 3.5 Flash (Medium)"
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

$backups = @()
$backups += Backup-File -Path $CodexConfig
$backups += Backup-File -Path $GeminiConfig
$backups += Backup-File -Path $IdeConfig

Set-CodexDevTriangleBlock -ConfigPath $CodexConfig -Block $codexBlock
Upsert-GeminiConfig -Path $GeminiConfig -ServerConfig $reportServerForGemini
Upsert-IdeConfig -Path $IdeConfig -ServerConfig $reportServerForIde

$result = [pscustomobject]@{
  status = "installed"
  name = "Dev Triangle MCP"
  toolRoot = $ToolRoot
  stateRoot = $StateRoot
  codexConfig = $CodexConfig
  geminiConfig = $GeminiConfig
  antigravityIdeConfig = $IdeConfig
  backups = @($backups | Where-Object { $_ })
  agy = if (Test-Path -LiteralPath $AgyPath) { $AgyPath } else { "not-found: $AgyPath" }
}

$result | ConvertTo-Json -Depth 5

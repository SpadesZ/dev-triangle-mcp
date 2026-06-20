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

$checks = [ordered]@{
  toolRoot = @{ ok = (Test-Path -LiteralPath $ToolRoot); value = $ToolRoot }
  stateRoot = @{ ok = (Test-Path -LiteralPath $StateRoot); value = $StateRoot }
  server = @{ ok = (Test-Path -LiteralPath (Join-Path $ToolRoot "server.py")); value = (Join-Path $ToolRoot "server.py") }
  reportServer = @{ ok = (Test-Path -LiteralPath (Join-Path $ToolRoot "antigravity_report_server.py")); value = (Join-Path $ToolRoot "antigravity_report_server.py") }
  python = Run-Command -FilePath $Python -Arguments @("--version")
  agy = Run-Command -FilePath $Agy -Arguments @("--version")
  codexConfigHasDevTriangle = @{ ok = ((Test-Path -LiteralPath $CodexConfig) -and ((Get-Content -Raw -LiteralPath $CodexConfig) -match [regex]::Escape((Join-Path $ToolRoot "server.py")))); value = $CodexConfig }
  geminiConfig = Test-JsonConfig -Path $GeminiConfig
  antigravityIdeConfig = Test-JsonConfig -Path $IdeConfig
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

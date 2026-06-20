param(
  [string]$ToolRoot = (Split-Path -Parent (Split-Path -Parent $PSCommandPath)),
  [string]$StateRoot = (Join-Path $HOME ".dev-triangle")
)

$ErrorActionPreference = "Stop"

function Invoke-Native {
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

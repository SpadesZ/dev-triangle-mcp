<#
.SYNOPSIS
Compatibility wrapper for the main protocol smoke test.

.DESCRIPTION
Kept for users who remember the original script name. New local installs should
prefer scripts/smoke.ps1 because it also checks the report server and agy
detection.
#>

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

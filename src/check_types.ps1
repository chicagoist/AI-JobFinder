# Static type checker for Gemini JobAgent (PowerShell)
# Usage: .\check_types.ps1
#        .\check_types.ps1 -Strict

param(
    [switch]$Strict
)

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $SCRIPT_DIR

if ($Strict) {
    Write-Host "=== Running mypy in STRICT mode ==="
    mypy job_agent/ --disallow-untyped-defs --disallow-incomplete-defs --config-file mypy.ini *>&1
} else {
    Write-Host "=== Running mypy (standard mode) ==="
    mypy job_agent/ --config-file mypy.ini *>&1
}

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "✅ All type checks passed!"
} else {
    Write-Host ""
    Write-Host "❌ Type errors found. Review and fix them."
    exit 1
}

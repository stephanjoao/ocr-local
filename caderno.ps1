$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Execute .\preparar.ps1 primeiro.'
}
& $pythonPath -X utf8 (Join-Path $PSScriptRoot 'caderno.py') @args
exit $LASTEXITCODE

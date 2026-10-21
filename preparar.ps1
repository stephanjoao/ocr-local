$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel criar o ambiente Python.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependencias.' }
Write-Host 'Ambiente pronto. Execute .\caderno.ps1 verificar e depois .\caderno.ps1.'

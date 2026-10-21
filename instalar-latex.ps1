$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072
$toolsDir = Join-Path $PSScriptRoot 'tools'
$executable = Join-Path $toolsDir 'tectonic.exe'
if (Test-Path -LiteralPath $executable) {
    & $executable --version
    exit $LASTEXITCODE
}
$release = Invoke-RestMethod -Uri 'https://api.github.com/repos/tectonic-typesetting/tectonic/releases/tags/tectonic%400.17.0'
$asset = @($release.assets | Where-Object { $_.name -match 'x86_64-pc-windows-msvc\.zip$' })
if ($asset.Count -ne 1) { throw 'Pacote oficial para Windows nao encontrado.' }
if ($asset[0].digest -notmatch '^sha256:([0-9a-f]{64})$') {
    throw 'O release nao informou SHA256 para validar o download.'
}
$expectedHash = $Matches[1]
New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
$archive = Join-Path $toolsDir $asset[0].name
Write-Host 'Baixando Tectonic oficial para compilar LaTeX localmente...'
Invoke-WebRequest -UseBasicParsing -Uri $asset[0].browser_download_url -OutFile $archive
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expectedHash) {
    throw 'SHA256 divergente. O pacote nao sera extraido.'
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($archive)
try {
    $entries = @($zip.Entries | Where-Object { $_.Name -eq 'tectonic.exe' })
    if ($entries.Count -ne 1) { throw 'Executavel nao encontrado no pacote.' }
    [IO.Compression.ZipFileExtensions]::ExtractToFile($entries[0], $executable, $false)
} finally {
    $zip.Dispose()
}
& $executable --version
if ($LASTEXITCODE -ne 0) { throw 'Tectonic nao iniciou corretamente.' }
Write-Host 'Pronto. Use .\rodar.ps1 --compile para gerar o PDF do lote.'

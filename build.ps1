# build.ps1
# Builds SapphireAssetIQ.exe inside an isolated build environment (.venv in this
# project folder), so the EXE contains only what this program needs. The shared
# DevEnv is never touched.
#
# Usage, from the project root:
#   .\build.ps1                         ONE EXE file, config.json + Google key built in (for AD)
#   .\build.ps1 -NoEmbed                one EXE file; config.json / service_account.json kept outside
#   .\build.ps1 -Mode Folder            EXE + _internal folder (starts faster, for troubleshooting)
#   .\build.ps1 -SignThumbprint <hex>   also sign the EXE with that code-signing certificate

param(
    [ValidateSet("OneFile", "Folder")] [string]$Mode = "OneFile",
    [switch]$NoEmbed,
    [string]$SignThumbprint = $env:SIF_SIGN_THUMBPRINT
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Host "[1/6] Build environment (.venv)..."
if (-not (Test-Path $py)) { python -m venv .venv }
if (-not (Test-Path $py)) { throw "Could not create .venv - is Python 3.10+ on PATH?" }

Write-Host "[2/6] Installing requirements.txt into .venv..."
& $py -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host "[3/6] Drawing the icon and writing the version details..."
& $py tools\build_assets.py build
if ($LASTEXITCODE -ne 0) { throw "Could not create build\app.ico / build\version_info.txt" }

$embed = ($Mode -eq "OneFile") -and (-not $NoEmbed)
$pyiArgs = @("--noconfirm", "--clean", "--windowed", "--name", "SapphireAssetIQ", "--paths", "src",
             "--icon", "build\app.ico", "--version-file", "build\version_info.txt")
if ($Mode -eq "OneFile") {
    $pyiArgs += "--onefile"
    $exe = Join-Path $PSScriptRoot "dist\SapphireAssetIQ.exe"
    $stale = Join-Path $PSScriptRoot "dist\SapphireAssetIQ"
    if (Test-Path -LiteralPath $stale -PathType Container) { [IO.Directory]::Delete($stale, $true) }
} else {
    $pyiArgs += "--onedir"
    $exe = Join-Path $PSScriptRoot "dist\SapphireAssetIQ\SapphireAssetIQ.exe"
    $stale = Join-Path $PSScriptRoot "dist\SapphireAssetIQ.exe"
    if (Test-Path -LiteralPath $stale -PathType Leaf) { [IO.File]::Delete($stale) }
}
if ($embed) {
    foreach ($name in "config.json", "service_account.json") {
        if (-not (Test-Path "src\$name")) { throw "src\$name is missing - it has to exist to be built into the EXE (or use -NoEmbed)" }
        $pyiArgs += @("--add-data", "src\$name;.")
    }
}

Write-Host "[4/6] Building ($Mode$(if ($embed) { ', config.json and Google key built in' }))..."
& $py -m PyInstaller @pyiArgs src\main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "[5/6] Settings files..."
if ($embed) {
    Write-Host "      built into the EXE. A config.json / service_account.json placed next to it still overrides them."
} else {
    $beside = Split-Path -Parent $exe
    foreach ($name in "config.json", "service_account.json") {
        if (Test-Path "src\$name") { Copy-Item -LiteralPath "src\$name" -Destination $beside -Force; Write-Host "      copied $name next to the EXE" }
        else { Write-Warning "src\$name not found - put it next to the EXE before running." }
    }
}

Write-Host "[6/6] Code signing..."
if ($SignThumbprint) {
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\x64\\' } | Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $signtool) { throw "signtool.exe not found - install the Windows SDK" }
    & $signtool.FullName sign /sha1 $SignThumbprint /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $exe
    if ($LASTEXITCODE -ne 0) { throw "Signing failed" }
} else {
    Write-Host "      skipped - no certificate given, so Windows will list the publisher as Unknown."
}

Write-Host ""
Write-Host "Done: $exe"
Write-Host "  AD / GPO     : \\<server>\NETLOGON\SapphireAssetIQ.exe            (no window at all; exit code 0 = saved)"
Write-Host "  Window       : SapphireAssetIQ.exe --window                       (testing, or running it by hand)"
Write-Host "  Before copying it to the share, clear any download mark so Windows does not warn about it:"
Write-Host "      Unblock-File '$exe'"

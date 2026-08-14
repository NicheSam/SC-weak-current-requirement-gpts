[CmdletBinding()]
param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = Join-Path $root ".runtime"
$uvDir = Join-Path $runtimeDir "uv"
$uvExe = Join-Path $uvDir "uv.exe"
$pythonDir = Join-Path $runtimeDir "python"
$cacheDir = Join-Path $runtimeDir "cache"
$venvDir = Join-Path $root ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$requirements = Join-Path $root "docling\requirements.in"

function Assert-LastExitCode {
    param([string]$Step)

    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
    throw "Requirements file was not found: $requirements"
}

if ($CheckOnly) {
    Write-Host "Installer configuration check passed."
    Write-Host "Runtime: $runtimeDir"
    Write-Host "Environment: $venvDir"
    exit 0
}

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null

if (-not (Test-Path -LiteralPath $uvExe -PathType Leaf)) {
    Write-Host "Downloading the private uv bootstrapper..."
    $env:UV_UNMANAGED_INSTALL = $uvDir
    $env:UV_NO_MODIFY_PATH = "1"
    $installerPath = Join-Path $runtimeDir "uv-installer.ps1"
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "https://astral.sh/uv/install.ps1" -OutFile $installerPath
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installerPath
        Assert-LastExitCode "uv bootstrapper installation"
    }
    finally {
        Remove-Item -LiteralPath $installerPath -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path -LiteralPath $uvExe -PathType Leaf)) {
    throw "uv was not installed at the expected location: $uvExe"
}

$env:UV_PYTHON_INSTALL_DIR = $pythonDir
$env:UV_CACHE_DIR = $cacheDir
$env:UV_NO_MODIFY_PATH = "1"
$env:PYTHONUTF8 = "1"

Write-Host "Preparing a private Python 3.12 runtime..."
& $uvExe --no-config --system-certs python install 3.12 --managed-python --no-bin --no-registry
Assert-LastExitCode "Python installation"

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    Write-Host "Creating the private Docling environment..."
    & $uvExe --no-config --system-certs venv --python 3.12 --managed-python $venvDir
    Assert-LastExitCode "Virtual environment creation"
}

Write-Host "Installing Docling and OCR dependencies..."
& $uvExe --no-config --system-certs pip install --python $venvPython --requirements $requirements
Assert-LastExitCode "Dependency installation"

Write-Host "Verifying the installed environment..."
& $venvPython -c "import docling; import rapidocr; print('Docling environment verified.')"
Assert-LastExitCode "Environment verification"

Write-Host "Installation is ready. Run launch_docling_ui.cmd."

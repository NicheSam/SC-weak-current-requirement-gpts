[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$SkipVCRuntimeInstall
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

trap {
    Write-Host ""
    Write-Host "INSTALL_ERROR|$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = Join-Path $root ".runtime"
$uvDir = Join-Path $runtimeDir "uv"
$uvExe = Join-Path $uvDir "uv.exe"
$pythonDir = Join-Path $runtimeDir "python"
$cacheDir = Join-Path $runtimeDir "cache"
$venvDir = Join-Path $root ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$requirements = Join-Path $root "docling\requirements.in"
$diagnostics = Join-Path $root "docling\runtime_diagnostics.py"
$minimumFreeBytes = 3GB

function Assert-LastExitCode {
    param([string]$Step)

    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

function Assert-HostEnvironment {
    if (-not [Environment]::Is64BitOperatingSystem -or -not [Environment]::Is64BitProcess) {
        throw "E_ARCH: This package requires 64-bit Windows and a 64-bit PowerShell process."
    }

    $driveRoot = [System.IO.Path]::GetPathRoot($root)
    $drive = New-Object System.IO.DriveInfo($driveRoot)
    if ($drive.AvailableFreeSpace -lt $minimumFreeBytes) {
        throw "E_DISK_SPACE: At least 3 GB of free disk space is required."
    }

    $probe = Join-Path $root ".docling-write-test.tmp"
    try {
        [System.IO.File]::WriteAllText($probe, "ok", [System.Text.Encoding]::ASCII)
    }
    catch {
        throw "E_PERMISSION: The installation folder is not writable. Move the package to a user-writable folder."
    }
    finally {
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-Download {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Description
    )

    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Destination
    }
    catch {
        throw "E_NETWORK: Failed to download $Description. Check Internet access, proxy, firewall, and TLS inspection settings. $($_.Exception.Message)"
    }
}

function Invoke-RuntimeDiagnostics {
    & $venvPython $diagnostics --tool-root $root | ForEach-Object { Write-Host $_ }
    $code = $LASTEXITCODE
    return $code
}

function Install-VCRuntime {
    $installerPath = Join-Path $runtimeDir "vc_redist.x64.exe"
    Write-Host "Microsoft Visual C++ Runtime is missing or cannot load."
    Write-Host "Downloading the official Microsoft x64 runtime..."
    Invoke-Download -Uri "https://aka.ms/vs/17/release/vc_redist.x64.exe" -Destination $installerPath -Description "Microsoft Visual C++ Runtime"
    try {
        Write-Host "Windows may request administrator approval for the Microsoft runtime installer."
        $process = Start-Process -FilePath $installerPath -ArgumentList "/install", "/quiet", "/norestart" -Verb RunAs -Wait -PassThru
        if ($process.ExitCode -notin @(0, 1638, 3010)) {
            throw "E_VC_RUNTIME: Microsoft Visual C++ Runtime installation failed with exit code $($process.ExitCode)."
        }
    }
    catch {
        throw "E_VC_RUNTIME: Microsoft Visual C++ Runtime could not be installed. Run vc_redist.x64.exe as administrator, then run install_docling.cmd again. $($_.Exception.Message)"
    }
    finally {
        Remove-Item -LiteralPath $installerPath -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
    throw "Requirements file was not found: $requirements"
}
if (-not (Test-Path -LiteralPath $diagnostics -PathType Leaf)) {
    throw "Runtime diagnostics file was not found: $diagnostics"
}

Assert-HostEnvironment

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
        Invoke-Download -Uri "https://astral.sh/uv/install.ps1" -Destination $installerPath -Description "uv bootstrapper"
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
$diagnosticExitCode = Invoke-RuntimeDiagnostics
if ($diagnosticExitCode -in @(20, 21) -and -not $SkipVCRuntimeInstall) {
    Install-VCRuntime
    $diagnosticExitCode = Invoke-RuntimeDiagnostics
}
if ($diagnosticExitCode -ne 0) {
    throw "Environment verification failed with diagnostic exit code $diagnosticExitCode. Review the DOC_ERR line above."
}

Write-Host "Installation is ready. Run launch_docling_ui.cmd."

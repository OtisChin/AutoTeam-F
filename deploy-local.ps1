param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8787,
    [switch]$NoStart,
    [switch]$SkipBrowserInstall,
    [switch]$ForceRecreate
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectRoot ".venv"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [string]$Description,
        [string]$Command,
        [string[]]$Arguments
    )

    Write-Step $Description
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

function Test-PythonCandidate {
    param([string[]]$Candidate)

    $cmd = $Candidate[0]
    $args = @()
    if ($Candidate.Count -gt 1) {
        $args = $Candidate[1..($Candidate.Count - 1)]
    }

    & $cmd @args -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
    return $LASTEXITCODE -eq 0
}

function Find-Python {
    $candidates = @()

    if ($env:PYTHON) {
        $candidates += ,@($env:PYTHON)
    }

    $candidates += ,@("py", "-3.10")
    $candidates += ,@("python")
    $candidates += ,@("python3")

    foreach ($candidate in $candidates) {
        try {
            if (Test-PythonCandidate -Candidate $candidate) {
                return $candidate
            }
        } catch {
            continue
        }
    }

    throw "Python 3.10+ was not found. Install Python 3.10 or newer, or set the PYTHON environment variable."
}

function Get-VenvPython {
    $windowsPython = Join-Path $VenvDir "Scripts\python.exe"
    if (Test-Path $windowsPython) {
        return $windowsPython
    }

    $unixPython = Join-Path $VenvDir "bin/python"
    if (Test-Path $unixPython) {
        return $unixPython
    }

    throw "Virtual environment Python was not found under $VenvDir"
}

Set-Location $ProjectRoot

if ($ForceRecreate -and (Test-Path $VenvDir)) {
    Write-Step "Removing existing .venv"
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
}

if (-not (Test-Path $VenvDir)) {
    $python = @(Find-Python)
    $pythonCmd = $python[0]
    $pythonArgs = @()
    if ($python.Count -gt 1) {
        $pythonArgs = $python[1..($python.Count - 1)]
    }

    Write-Step "Creating .venv"
    & $pythonCmd @pythonArgs -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Creating .venv failed with exit code $LASTEXITCODE"
    }
} else {
    Write-Step "Using existing .venv"
}

$VenvPython = Get-VenvPython

& $VenvPython -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
    Invoke-Checked -Description "Bootstrapping pip in .venv" -Command $VenvPython -Arguments @("-m", "ensurepip", "--upgrade")
}

Invoke-Checked -Description "Upgrading pip tooling" -Command $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")
Invoke-Checked -Description "Installing AutoTeam-F with pip" -Command $VenvPython -Arguments @("-m", "pip", "install", "-e", ".")

if (-not $SkipBrowserInstall) {
    Invoke-Checked -Description "Installing Playwright Chromium" -Command $VenvPython -Arguments @("-m", "playwright", "install", "chromium")
} else {
    Write-Step "Skipping Playwright Chromium install"
}

$envFile = Join-Path $ProjectRoot ".env"
$envExample = Join-Path $ProjectRoot ".env.example"
if (-not (Test-Path $envFile) -and (Test-Path $envExample)) {
    Write-Step "Creating .env from .env.example"
    Copy-Item -LiteralPath $envExample -Destination $envFile
    Write-Host "Created .env. Fill it in from the web setup page or edit it manually."
}

Write-Step "Deployment complete"
Write-Host "Virtual environment: $VenvDir"
Write-Host "Web panel: http://$HostAddress`:$Port"

if (-not $NoStart) {
    Write-Step "Starting AutoTeam-F API and web panel"
    & $VenvPython -m autoteam api --host $HostAddress --port $Port
    exit $LASTEXITCODE
}

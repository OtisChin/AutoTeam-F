param(
    [switch]$NoConsole,
    [switch]$SkipWebBuild
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    uv sync

    if (-not $SkipWebBuild) {
        Push-Location "web"
        try {
            npm install
            npm run build
        }
        finally {
            Pop-Location
        }
    }

    $env:PLAYWRIGHT_BROWSERS_PATH = "0"
    uv run playwright install chromium

    $consoleMode = if ($NoConsole) { "--noconsole" } else { "--console" }
    $args = @(
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", "autoteam",
        $consoleMode,
        "--collect-all", "playwright",
        "--collect-all", "curl_cffi",
        "--collect-data", "certifi",
        "--collect-submodules", "uvicorn",
        "--collect-submodules", "httptools",
        "--collect-submodules", "websockets",
        "--collect-submodules", "watchfiles",
        "--add-data", "src\autoteam\web\dist;autoteam\web\dist",
        "--add-data", "src\autoteam\oauth_helper_extension;autoteam\oauth_helper_extension",
        "src\autoteam\__main__.py"
    )

    uv run --with pyinstaller pyinstaller @args
}
finally {
    Pop-Location
}


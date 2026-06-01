$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $root "config.json"

function Get-DefaultProxyApiUrl([string]$provider) {
    if ($provider -eq "1024proxy") {
        return "https://white.1024proxy.com/white/api?region=ID&num=1&time=10&format=1&type=json"
    }
    return "https://api.cliproxy.io/white/api?region=ID&num=1&time=10&format=n&type=txt"
}

function Normalize-Provider([string]$provider) {
    $normalized = (($provider -as [string]).ToLower() -replace "[^a-z0-9]", "")
    if ($normalized -in @("1024proxy", "1024")) { return "1024proxy" }
    return "cliproxy"
}

function Find-ProxyCandidate($value) {
    if ($null -eq $value) { return "" }
    if ($value -is [string]) {
        $text = $value.Trim()
        if (-not $text) { return "" }
        try {
            $json = $text | ConvertFrom-Json -ErrorAction Stop
            $candidate = Find-ProxyCandidate $json
            if ($candidate) { return $candidate }
        } catch {}
        foreach ($line in ($text -split "[\r\n,]+")) {
            $item = $line.Trim()
            if ($item) { return $item }
        }
        return ""
    }
    if ($value -is [System.Array]) {
        foreach ($item in $value) {
            $candidate = Find-ProxyCandidate $item
            if ($candidate) { return $candidate }
        }
        return ""
    }
    if ($value -is [pscustomobject]) {
        $names = @("proxy", "Proxy", "result", "data", "list", "proxies", "proxy_list", "proxyList", "host", "ip", "addr", "address")
        foreach ($name in $names) {
            if ($value.PSObject.Properties.Name -contains $name) {
                $propertyValue = $value.$name
                if ($name -in @("host", "ip", "addr", "address") -and ($value.PSObject.Properties.Name -contains "port")) {
                    return "$propertyValue`:$($value.port)"
                }
                $candidate = Find-ProxyCandidate $propertyValue
                if ($candidate) { return $candidate }
            }
        }
        foreach ($prop in $value.PSObject.Properties) {
            $candidate = Find-ProxyCandidate $prop.Value
            if ($candidate) { return $candidate }
        }
    }
    return ""
}

function Normalize-ProxyUrl([string]$candidate, [string]$provider) {
    $proxy = ($candidate -as [string]).Trim()
    if (-not $proxy) { return "" }
    if ($proxy -notmatch "^[a-zA-Z][a-zA-Z0-9+.-]*://") {
        if ($provider -eq "cliproxy") {
            $proxy = "socks5://$proxy"
        } else {
            $proxy = "http://$proxy"
        }
    }
    try {
        $uri = [Uri]$proxy
        if (-not $uri.Host -or -not $uri.Port) {
            throw "missing host or port"
        }
    } catch {
        throw "proxy API returned an invalid proxy"
    }
    return $proxy
}

function Test-ProxyUrl([string]$proxyUrl) {
    if ($proxyUrl -match "^socks5h?://") {
        try {
            $target = $proxyUrl -replace "^socks5h?://", ""
            $output = & curl.exe --silent --show-error --max-time 12 --socks5-hostname $target http://api.ipify.org 2>$null
            $ip = ($output -as [string]).Trim()
            if ($LASTEXITCODE -eq 0 -and $ip.Length -gt 0 -and $ip.Length -lt 80) {
                return $ip
            }
        } catch {}
        return ""
    }
    try {
        $response = Invoke-WebRequest -Uri "http://api.ipify.org" -Proxy $proxyUrl -UseBasicParsing -TimeoutSec 12
        if ([int]$response.StatusCode -ge 400) {
            return ""
        }
        $ip = ($response.Content -as [string]).Trim()
        if ($ip.Length -gt 0 -and $ip.Length -lt 80) {
            return $ip
        }
    } catch {}
    return ""
}

function Mask-Proxy([string]$proxyUrl) {
    try {
        $uri = [Uri]$proxyUrl
        $port = ""
        if ($uri.Port -gt 0) {
            $port = ":" + $uri.Port
        }
        return "$($uri.Scheme)://***@$($uri.Host)$port"
    } catch {
        return "***"
    }
}

function Write-Utf8NoBom([string]$path, [string]$text) {
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($path, $text, $encoding)
}

if (-not (Test-Path -LiteralPath $configPath)) {
    Write-Host "[proxy] config.json not found, skip proxy API"
    exit 0
}

$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($null -eq $config.pool) {
    $config | Add-Member -NotePropertyName pool -NotePropertyValue ([pscustomobject]@{}) -Force
}
if ($null -eq $config.pool.proxy_api) {
    $config.pool | Add-Member -NotePropertyName proxy_api -NotePropertyValue ([pscustomobject]@{}) -Force
}

$proxyApi = $config.pool.proxy_api
$enabled = [bool]$proxyApi.enabled
if (-not $enabled) {
    Write-Host "[proxy] proxy API disabled, keep existing proxy_id"
    exit 0
}

$provider = Normalize-Provider $proxyApi.provider
$apiUrl = ($proxyApi.url -as [string]).Trim()
if (-not $apiUrl) {
    $apiUrl = Get-DefaultProxyApiUrl $provider
    $proxyApi | Add-Member -NotePropertyName url -NotePropertyValue $apiUrl -Force
}
$proxyApi | Add-Member -NotePropertyName provider -NotePropertyValue $provider -Force

$proxyUrl = ""
$exitIp = ""
$maxAttempts = 5
for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    Write-Host "[proxy] reg.cmd fetching Indonesia proxy from $provider API (attempt $attempt/$maxAttempts)"
    $response = Invoke-WebRequest -Uri $apiUrl -UseBasicParsing -TimeoutSec 30
    if ([int]$response.StatusCode -ge 400) {
        throw "proxy API returned HTTP $($response.StatusCode)"
    }
    $text = ($response.Content -as [string]).Trim()
    if ($text -match "(?is)^\s*<!doctype\s+html\b|^\s*<html\b") {
        throw "proxy API returned HTML, check API URL, whitelist or plan"
    }
    $candidate = Find-ProxyCandidate $text
    $candidateProxyUrl = Normalize-ProxyUrl $candidate $provider
    if (-not $candidateProxyUrl) {
        Write-Host "[proxy] proxy API returned empty proxy, retrying"
        Start-Sleep -Seconds 1
        continue
    }
    $candidateExitIp = Test-ProxyUrl $candidateProxyUrl
    if ($candidateExitIp) {
        $proxyUrl = $candidateProxyUrl
        $exitIp = $candidateExitIp
        break
    }
    Write-Host "[proxy] proxy probe failed: $(Mask-Proxy $candidateProxyUrl), retrying"
    Start-Sleep -Seconds 1
}
if (-not $proxyUrl) {
    throw "proxy API did not return a reachable proxy after $maxAttempts attempts"
}

$config | Add-Member -NotePropertyName proxy_id -NotePropertyValue $proxyUrl -Force
$json = $config | ConvertTo-Json -Depth 50
Write-Utf8NoBom $configPath ($json + "`n")
Write-Host "[proxy] reg.cmd switched to $provider Indonesia proxy: $(Mask-Proxy $proxyUrl) exit_ip=$exitIp"

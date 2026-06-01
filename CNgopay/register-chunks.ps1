$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $root "config.json"
$statePath = Join-Path $root "runs\pool\state.json"
$cooldownPath = Join-Path $root "runs\pool\cooldowns.json"
$poolExe = if ($env:CNGOPAY_POOL_EXE) { $env:CNGOPAY_POOL_EXE } else { Join-Path $root "pool.exe" }
$prepareProxy = if ($env:CNGOPAY_PREPARE_PROXY_SCRIPT) { $env:CNGOPAY_PREPARE_PROXY_SCRIPT } else { Join-Path $root "prepare-register-proxy.ps1" }
$rateLimitCooldownSeconds = 60 * 60
$script:LastRegisterExitCode = 0

function Get-IntValue($value, [int]$fallback) {
    try {
        $num = [int]$value
        if ($num -gt 0) { return $num }
    } catch {}
    return $fallback
}

function Get-ActiveNumberCount($config, [string]$rootPath) {
    $numberFile = "pool_numbers.txt"
    if ($null -ne $config.pool -and $config.pool.PSObject.Properties.Name -contains "number_pool_file") {
        $candidate = ($config.pool.number_pool_file -as [string]).Trim()
        if ($candidate) { $numberFile = $candidate }
    }
    if ([System.IO.Path]::IsPathRooted($numberFile)) {
        $path = $numberFile
    } else {
        $path = Join-Path $rootPath $numberFile
    }
    if (-not (Test-Path -LiteralPath $path)) { return 0 }
    $count = 0
    foreach ($line in Get-Content -LiteralPath $path -Encoding UTF8) {
        $text = ($line -as [string]).Trim()
        if ($text -and -not $text.StartsWith("#")) {
            $count += 1
        }
    }
    return $count
}

function Write-Utf8NoBom([string]$path, [string]$text) {
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($path, $text, $encoding)
}

function Save-Config($config, [string]$path) {
    $json = $config | ConvertTo-Json -Depth 50
    Write-Utf8NoBom $path ($json + "`n")
}

function Read-JsonFile([string]$path, $fallback) {
    if (-not (Test-Path -LiteralPath $path)) { return $fallback }
    try {
        $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8
        if (-not $text.Trim()) { return $fallback }
        return $text | ConvertFrom-Json
    } catch {
        return $fallback
    }
}

function Save-JsonFile([string]$path, $value) {
    $parent = Split-Path -Parent $path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $json = $value | ConvertTo-Json -Depth 80
    Write-Utf8NoBom $path ($json + "`n")
}

function Get-UnixNow() {
    return [int64][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
}

function Get-SlotIndex([string]$slotId) {
    $match = [regex]::Match($slotId, "(\d+)$")
    if (-not $match.Success) { return 0 }
    return [int]$match.Groups[1].Value
}

function Test-RateLimitedText([string]$text) {
    if (-not $text) { return $false }
    return $text -match "ratelimited|rate\s*limit|限流|60\s*分钟"
}

function Get-ObjectProperty($obj, [string]$name) {
    if ($null -eq $obj) { return $null }
    $prop = $obj.PSObject.Properties[$name]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

function Set-ObjectProperty($obj, [string]$name, $value) {
    $prop = $obj.PSObject.Properties[$name]
    if ($null -eq $prop) {
        $obj | Add-Member -NotePropertyName $name -NotePropertyValue $value -Force
    } else {
        $prop.Value = $value
    }
}

function Read-Cooldowns() {
    $cooldowns = Read-JsonFile $cooldownPath ([pscustomobject]@{ slots = [pscustomobject]@{} })
    if ($null -eq $cooldowns.slots) {
        $cooldowns | Add-Member -NotePropertyName slots -NotePropertyValue ([pscustomobject]@{}) -Force
    }
    return $cooldowns
}

function Prune-Cooldowns($cooldowns) {
    $now = Get-UnixNow
    $changed = $false
    foreach ($prop in @($cooldowns.slots.PSObject.Properties)) {
        $until = [int64](Get-ObjectProperty $prop.Value "until")
        if ($until -le $now) {
            $cooldowns.slots.PSObject.Properties.Remove($prop.Name)
            $changed = $true
        }
    }
    if ($changed) {
        $cooldowns | Add-Member -NotePropertyName updated_at -NotePropertyValue $now -Force
        Save-JsonFile $cooldownPath $cooldowns
    }
    return $cooldowns
}

function Add-RatelimitCooldownsFromState([int64]$runStartedAt) {
    $state = Read-JsonFile $statePath ([pscustomobject]@{ slots = [pscustomobject]@{} })
    if ($null -eq $state.slots) { return }
    $cooldowns = Prune-Cooldowns (Read-Cooldowns)
    $now = Get-UnixNow
    $changed = $false
    foreach ($prop in @($state.slots.PSObject.Properties)) {
        $slotId = $prop.Name
        $slot = $prop.Value
        if ($null -eq $slot) { continue }
        $stateName = [string](Get-ObjectProperty $slot "state")
        if ($stateName -ne "FAILED") { continue }
        $errorText = [string](Get-ObjectProperty $slot "error")
        if (-not (Test-RateLimitedText $errorText)) { continue }
        $existingCooldown = Get-ObjectProperty $cooldowns.slots $slotId
        $existingUntil = [int64](Get-ObjectProperty $existingCooldown "until")
        if ($existingUntil -gt $now) { continue }
        $updatedAt = [int64](Get-ObjectProperty $slot "updated_at")
        if ($updatedAt -gt 0 -and $updatedAt -lt ($runStartedAt - 60)) { continue }
        $until = $now + $rateLimitCooldownSeconds
        Set-ObjectProperty $cooldowns.slots $slotId ([pscustomobject]@{
            until = $until
            phone = [string](Get-ObjectProperty $slot "full_phone")
            reason = "GoPay ratelimited"
            error = $errorText
            updated_at = $now
        })
        Set-ObjectProperty $slot "cooldown_until" $until
        Set-ObjectProperty $slot "cooldown_reason" "GoPay ratelimited"
        Write-Host "[cooldown] $slotId GoPay 限流，冷却 60 分钟后再注册"
        $changed = $true
    }
    if ($changed) {
        $cooldowns | Add-Member -NotePropertyName updated_at -NotePropertyValue $now -Force
        Save-JsonFile $cooldownPath $cooldowns
        Save-JsonFile $statePath $state
    }
}

function Seed-ExistingRatelimitCooldowns() {
    $state = Read-JsonFile $statePath ([pscustomobject]@{ slots = [pscustomobject]@{} })
    if ($null -eq $state.slots) { return }
    $cooldowns = Prune-Cooldowns (Read-Cooldowns)
    $now = Get-UnixNow
    $changed = $false
    foreach ($prop in @($state.slots.PSObject.Properties)) {
        $slotId = $prop.Name
        $slot = $prop.Value
        if ($null -eq $slot) { continue }
        if ([string](Get-ObjectProperty $slot "state") -ne "FAILED") { continue }
        $errorText = [string](Get-ObjectProperty $slot "error")
        if (-not (Test-RateLimitedText $errorText)) { continue }
        $existingCooldown = Get-ObjectProperty $cooldowns.slots $slotId
        if ([int64](Get-ObjectProperty $existingCooldown "until") -gt $now) { continue }
        $updatedAt = [int64](Get-ObjectProperty $slot "updated_at")
        if ($updatedAt -le 0) { continue }
        $until = $updatedAt + $rateLimitCooldownSeconds
        if ($until -le $now) { continue }
        Set-ObjectProperty $cooldowns.slots $slotId ([pscustomobject]@{
            until = $until
            phone = [string](Get-ObjectProperty $slot "full_phone")
            reason = "GoPay ratelimited"
            error = $errorText
            updated_at = $now
        })
        Set-ObjectProperty $slot "cooldown_until" $until
        Set-ObjectProperty $slot "cooldown_reason" "GoPay ratelimited"
        $remainingMinutes = [Math]::Max(1, [Math]::Ceiling(($until - $now) / 60))
        Write-Host "[cooldown] $slotId existing GoPay 限流，剩余冷却 $remainingMinutes min"
        $changed = $true
    }
    if ($changed) {
        $cooldowns | Add-Member -NotePropertyName updated_at -NotePropertyValue $now -Force
        Save-JsonFile $cooldownPath $cooldowns
        Save-JsonFile $statePath $state
    }
}

function Apply-CooldownSkips([int]$chunkEnd) {
    $cooldowns = Prune-Cooldowns (Read-Cooldowns)
    $state = Read-JsonFile $statePath ([pscustomobject]@{ slots = [pscustomobject]@{} })
    if ($null -eq $state.slots) { return ,@{} }
    $now = Get-UnixNow
    $restore = @{}
    foreach ($prop in @($cooldowns.slots.PSObject.Properties)) {
        $slotId = $prop.Name
        $slotIndex = Get-SlotIndex $slotId
        if ($slotIndex -le 0 -or $slotIndex -gt $chunkEnd) { continue }
        $cooldown = $prop.Value
        $until = [int64](Get-ObjectProperty $cooldown "until")
        if ($until -le $now) { continue }
        $slot = Get-ObjectProperty $state.slots $slotId
        if ($null -eq $slot) { continue }
        $stateName = [string](Get-ObjectProperty $slot "state")
        if ($stateName -eq "WALLET_READY") { continue }
        $restore[$slotId] = ($slot | ConvertTo-Json -Depth 80 | ConvertFrom-Json)
        Set-ObjectProperty $slot "state" "WALLET_READY"
        Set-ObjectProperty $slot "error" "AutoTeam cooldown skip: GoPay ratelimited until $until"
        Set-ObjectProperty $slot "cooldown_until" $until
        $remainingMinutes = [Math]::Max(1, [Math]::Ceiling(($until - $now) / 60))
        Write-Host "[cooldown] skip $slotId for $remainingMinutes min (GoPay ratelimited)"
    }
    if ($restore.Count -gt 0) {
        Save-JsonFile $statePath $state
    }
    return ,$restore
}

function Restore-CooldownSkips($restore) {
    if ($null -eq $restore -or $restore.Count -le 0) { return }
    $state = Read-JsonFile $statePath ([pscustomobject]@{ slots = [pscustomobject]@{} })
    if ($null -eq $state.slots) { return }
    foreach ($slotId in $restore.Keys) {
        Set-ObjectProperty $state.slots $slotId $restore[$slotId]
    }
    Save-JsonFile $statePath $state
}

function Invoke-RegisterChunk([string]$poolPath, [object[]]$extraArgs, [int]$chunkEnd) {
    $runStartedAt = Get-UnixNow
    $restore = Apply-CooldownSkips $chunkEnd
    & $poolPath -config config.json -mode register @extraArgs
    $code = $LASTEXITCODE
    $script:LastRegisterExitCode = $code
    Restore-CooldownSkips $restore
    Add-RatelimitCooldownsFromState $runStartedAt
    if ($code -ne 0) {
        Write-Host "[proxy] register chunk finished with exit_code=$code; continue next chunk because slot-level failures are expected"
    }
}

if (-not (Test-Path -LiteralPath $configPath)) {
    throw "config.json not found"
}
if (-not (Test-Path -LiteralPath $poolExe)) {
    throw "pool.exe not found"
}

$originalConfigText = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
$config = $originalConfigText | ConvertFrom-Json
if ($null -eq $config.pool) {
    $config | Add-Member -NotePropertyName pool -NotePropertyValue ([pscustomobject]@{}) -Force
}
if ($null -eq $config.pool.proxy_api) {
    $config.pool | Add-Member -NotePropertyName proxy_api -NotePropertyValue ([pscustomobject]@{}) -Force
}

$activeNumberCount = Get-ActiveNumberCount $config $root
$configuredSlots = Get-IntValue $config.pool.slots $activeNumberCount
$configuredConcurrency = Get-IntValue $config.pool.concurrency 1
$proxyEnabled = [bool]$config.pool.proxy_api.enabled
$chunkSize = Get-IntValue $config.pool.proxy_api.chunk_size $configuredConcurrency
$explicitTotalSlots = Get-IntValue $env:CNGOPAY_REGISTER_TOTAL_SLOTS 0
if ($explicitTotalSlots -gt 0) {
    $totalSlots = $explicitTotalSlots
} elseif ($proxyEnabled -and $activeNumberCount -gt 0) {
    $totalSlots = $activeNumberCount
} else {
    $totalSlots = $configuredSlots
}
$totalSlots = [Math]::Max(1, $totalSlots)
Seed-ExistingRatelimitCooldowns

if (-not $proxyEnabled -or $chunkSize -le 0 -or $chunkSize -ge $totalSlots) {
    if ($proxyEnabled) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $prepareProxy
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    Invoke-RegisterChunk $poolExe $args $totalSlots
    exit $script:LastRegisterExitCode
}

Write-Host "[proxy] split register: total_slots=$totalSlots chunk_size=$chunkSize"

try {
    for ($chunkEnd = $chunkSize; $chunkEnd -le $totalSlots; $chunkEnd += $chunkSize) {
        $chunkConcurrency = [Math]::Max(1, [Math]::Min($configuredConcurrency, $chunkSize))
        $config.pool.slots = $chunkEnd
        $config.pool.concurrency = $chunkConcurrency
        Save-Config $config $configPath
        & powershell -NoProfile -ExecutionPolicy Bypass -File $prepareProxy
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Host "[proxy] register chunk: slots=1..$chunkEnd concurrency=$chunkConcurrency"
        Invoke-RegisterChunk $poolExe $args $chunkEnd
    }

    if (($totalSlots % $chunkSize) -ne 0) {
        $chunkConcurrency = [Math]::Max(1, [Math]::Min($configuredConcurrency, $chunkSize))
        $config.pool.slots = $totalSlots
        $config.pool.concurrency = $chunkConcurrency
        Save-Config $config $configPath
        & powershell -NoProfile -ExecutionPolicy Bypass -File $prepareProxy
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Host "[proxy] register chunk: slots=1..$totalSlots concurrency=$chunkConcurrency"
        Invoke-RegisterChunk $poolExe $args $totalSlots
    }
} finally {
    Write-Utf8NoBom $configPath $originalConfigText
}

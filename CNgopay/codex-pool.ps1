# codex-pool.ps1 -- concurrent codex registration with isolated hotmail sub-pools
#
# Usage: .\codex-pool.cmd 4
#
# Each worker gets one hotmail line via HOTMAIL_TOKENS_FILE env var,
# avoiding race condition on the shared pool_emails.txt.

param(
    [int]$N = 3,
    [switch]$ST = $true
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$emailsFile = Join-Path $root "pool_emails.txt"
$tmpDir = Join-Path $root "tmp\codex-workers"
$logsDir = Join-Path $root "tmp\codex-logs"
New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null

if (-not (Test-Path $emailsFile)) {
    Write-Error "$emailsFile not found"
    exit 1
}

$allLines = Get-Content $emailsFile | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith("#") }
if ($allLines.Count -lt $N) {
    Write-Error "pool_emails.txt only has $($allLines.Count) lines, need N=$N"
    exit 1
}

$workerFiles = @()
for ($i = 1; $i -le $N; $i++) {
    $wf = Join-Path $tmpDir "worker-$i.txt"
    $line = $allLines[$i - 1]
    Set-Content -Path $wf -Value "$line" -Encoding utf8 -NoNewline
    Add-Content -Path $wf -Value "" -Encoding utf8
    $workerFiles += $wf
}

$historyFile = Join-Path $root "hotmail_inbox.history.txt"
$ts = (Get-Date).ToString("o")
for ($i = 0; $i -lt $N; $i++) {
    Add-Content -Path $historyFile -Value "# split-to-worker at $ts" -Encoding utf8
    Add-Content -Path $historyFile -Value $allLines[$i] -Encoding utf8
}
$remaining = $allLines | Select-Object -Skip $N
if ($remaining) {
    Set-Content -Path $emailsFile -Value (($remaining -join "`n") + "`n") -Encoding utf8 -NoNewline
} else {
    Set-Content -Path $emailsFile -Value "" -Encoding utf8 -NoNewline
}

Write-Host "[pool] starting $N concurrent codex workers" -Foreground Cyan

$jpProxy = "socks5://USERNAME-region-JP:PASSWORD@HOST:PORT"
$usProxy = "http://USERNAME-region-US:PASSWORD@HOST:PORT"
$cwd = Join-Path $root "codex_register"
$useSt = $ST.IsPresent

$jobs = @()
for ($i = 1; $i -le $N; $i++) {
    $logFile = Join-Path $logsDir "worker-$i.log"
    # 删旧 log（如果存在），让 Tee-Object -Append 写入干净文件
    Remove-Item -Path $logFile -Force -ErrorAction SilentlyContinue
    $hotmailFile = $workerFiles[$i - 1]
    $job = Start-Job -ScriptBlock {
        param($cwd, $useSt, $jpProxy, $usProxy, $hotmailFile, $logFile)
        $env:HOTMAIL_TOKENS_FILE = $hotmailFile
        $env:SENTINEL_BROWSER_PROXY = $usProxy
        # 强制 npm 输出 UTF-8（Windows cmd 默认 GBK，Tee-Object 写出来乱码）
        $env:LANG = "en_US.UTF-8"
        $OutputEncoding = [System.Text.Encoding]::UTF8
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        Set-Location $cwd
        $cliArgs = @("run", "dev", "--", "--codex-cpa", "--gp-token-out", "../pool_tokens.txt", "--probe-trial-jp", $jpProxy)
        if ($useSt) { $cliArgs += "--st" }
        # 改用 Out-File -Encoding utf8（避免 Tee-Object 的默认编码问题）
        & npm.cmd $cliArgs 2>&1 | ForEach-Object { $_ | Tee-Object -FilePath $logFile -Append; $_ }
    } -ArgumentList $cwd, $useSt, $jpProxy, $usProxy, $hotmailFile, $logFile
    $jobs += @{Id = $i; Job = $job; Log = $logFile; Hotmail = $hotmailFile}
    $msg = "  worker-" + $i + " started (jobId=" + $job.Id + ", log=" + $logFile + ")"
    Write-Host $msg -Foreground Gray
}

Write-Host ""
Write-Host "[pool] $N workers running, logs in tmp\codex-logs\" -Foreground Yellow

while ($jobs | Where-Object { $_.Job.State -eq "Running" }) {
    Start-Sleep 5
    foreach ($entry in $jobs) {
        $state = $entry.Job.State
        if ($state -eq "Running") {
            $tail = ""
            if (Test-Path $entry.Log) {
                $tail = Get-Content $entry.Log -Tail 1 -ErrorAction SilentlyContinue
            }
            Write-Host ("  worker-" + $entry.Id + " [" + $state + "] " + $tail) -Foreground DarkGray
            # 已 npm 成功结束（codex-cpa 成功）但 Job 没被标 Completed → 主动结束这个 Job
            if (Test-Path $entry.Log) {
                $logTail = Get-Content $entry.Log -Tail 30 -ErrorAction SilentlyContinue | Out-String
                if ($logTail -match "codex-cpa") {
                    if ($logTail -match "no_trial|exit 2|exit\s*\(2\)" -or $logTail -match "(success|cpa-cpa|CPA token)") {
                        # 给 Tee 一点时间 flush，然后强制 stop
                        Start-Sleep 2
                        Stop-Job -Job $entry.Job -ErrorAction SilentlyContinue
                    }
                }
            }
        }
    }
}

Write-Host ""
Write-Host "[pool] all done, summary:" -Foreground Cyan
$success = 0
$fail = 0
foreach ($entry in $jobs) {
    $job = $entry.Job
    Receive-Job -Job $job | Out-Null
    $status = "fail"
    if ($job.State -eq "Completed") {
        $logTail = Get-Content $entry.Log -Tail 30 -ErrorAction SilentlyContinue | Out-String
        if ($logTail -match "codex-cpa") {
            if ($logTail -match "no trial|amount=" -and $logTail -notmatch "amount=0") {
                $status = "no-trial"
            } elseif ($logTail -match "success|cpa") {
                $status = "ok"
            }
        }
    }
    if ($status -eq "ok") {
        Write-Host ("  worker-" + $entry.Id + " OK") -Foreground Green
        $success++
    } else {
        Write-Host ("  worker-" + $entry.Id + " FAIL (see " + $entry.Log + ")") -Foreground Red
        $fail++
    }
    Remove-Job -Job $job
}

Write-Host ""
$tokenFile = Join-Path $root "pool_tokens.txt"
$tokenCount = 0
if (Test-Path $tokenFile) {
    $tokenCount = (Get-Content $tokenFile | Where-Object { $_.Trim() } | Measure-Object).Count
}
Write-Host ("[pool] success=" + $success + " fail=" + $fail + " total=" + $N + " | pool_tokens=" + $tokenCount) -Foreground Cyan

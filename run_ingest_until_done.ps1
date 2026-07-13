# Supervises the resumable IBKR backfill: re-runs `auto` until `status` reports the data
# has caught up to the present. Survives gateway disconnects that kill the process (each
# pass resumes gap-free from the frontier). Safe to leave running overnight.
#
#   powershell -ExecutionPolicy Bypass -File .\run_ingest_until_done.ps1
#
# Keep IB Gateway/TWS running (set it to auto-restart, not daily logout).

$ErrorActionPreference = "Continue"
$py = ".\.venv\Scripts\python.exe"
$maxPasses = 300

for ($i = 1; $i -le $maxPasses; $i++) {
    Write-Host "=== ingest pass $i @ $(Get-Date -Format u) ===" -ForegroundColor Cyan
    & $py -m qrp.ingestion --config config --mode auto

    & $py -m qrp.ingestion --config config --mode status
    if ($LASTEXITCODE -eq 0) {
        Write-Host "=== backfill complete after $i pass(es) ===" -ForegroundColor Green
        exit 0
    }

    Write-Host "not caught up yet; retrying in 30s..." -ForegroundColor Yellow
    Start-Sleep -Seconds 30
}

Write-Host "reached max passes ($maxPasses) without completing; inspect the logs." -ForegroundColor Red
exit 1

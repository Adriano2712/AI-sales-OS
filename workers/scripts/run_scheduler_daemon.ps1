# Keeps workers/scheduler.py running continuously, restarting it if it ever
# exits. scheduler.py already survives a bad tick internally (each sweep is
# wrapped in its own try/except, see main()'s loop) -- this loop is the
# outer safety net for the process itself dying (e.g. an unhandled error
# outside those try blocks, or the machine's Python/venv being touched
# while it's running).
#
# Registered as the "AISalesOS-Scheduler" Scheduled Task (see
# docs/DEPLOYMENT.md) -- not meant to be run by hand except to test it.

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repoRoot

# See _load_dotenv.ps1's own comment: python's Settings reads .env
# internally but never exports it to the real process environment, and
# some values (MIGRATIONS_DATABASE_URL) are read directly via os.environ,
# not through Settings at all -- python needs this process's environment
# to already have them.
. (Join-Path $PSScriptRoot "_load_dotenv.ps1") -EnvFilePath (Join-Path $repoRoot ".env")

$logDir = Join-Path $repoRoot "workers\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "scheduler.log"

$python = Join-Path $repoRoot "apps\api\.venv\Scripts\python.exe"

while ($true) {
    Add-Content -Path $logFile -Value "$(Get-Date -Format o) [daemon] starting workers/scheduler.py" -Encoding utf8
    # `2>&1 | Out-File -Encoding utf8`, not `*>>` -- PowerShell 5.1's native
    # redirection operators write UTF-16LE, which every other log/tool in
    # this project (plain UTF-8) reads back as garbled double-spaced text.
    # `-u`: python full-buffers stdout when it isn't a real console (piped,
    # same as here) -- without it, log lines sit in the buffer for a long
    # time instead of appearing as the process actually produces them.
    & $python "-u" "workers\scheduler.py" 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
    Add-Content -Path $logFile -Value "$(Get-Date -Format o) [daemon] workers/scheduler.py exited (code $LASTEXITCODE) -- restarting in 10s" -Encoding utf8
    Start-Sleep -Seconds 10
}

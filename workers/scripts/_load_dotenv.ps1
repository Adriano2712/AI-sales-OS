# Dot-sourced by run_worker_daemon.ps1 and run_scheduler_daemon.ps1.
#
# pydantic-settings' `env_file=".env"` (app.core.config.Settings) reads
# key/value pairs straight out of the file for the fields it declares --
# it never injects them into the process's real environment. That's fine
# for every setting Settings actually declares, but MIGRATIONS_DATABASE_URL
# is deliberately NOT one of them (see docs/DATABASE.md: only Alembic and
# narrow admin scripts should ever touch it) and is read via a bare
# `os.environ.get("MIGRATIONS_DATABASE_URL")` instead (same pattern as
# database/seeds/seed_dev_tenant.py) -- which stays unset unless something
# has actually exported it into the environment first. A human running
# these scripts by hand always did that themselves (`source .env` in bash,
# or an explicit `$env:...=` in PowerShell); a Scheduled Task launching
# python directly has no shell session to inherit that from, so this
# loads .env into *this* process's environment before python ever starts
# -- child processes launched via `&` inherit it automatically.
#
# Found the hard way running the persistent daemon for the first time:
# every "for every tenant" scheduler sweep failed with "MIGRATIONS_DATABASE_URL
# must be set" the moment it ran unattended, despite working fine in every
# manual test that had `.env` sourced into the shell beforehand.

param(
    [Parameter(Mandatory = $true)]
    [string]$EnvFilePath
)

if (-not (Test-Path $EnvFilePath)) {
    return
}

Get-Content -Path $EnvFilePath -Encoding utf8 | ForEach-Object {
    $line = $_.Trim()
    if ($line.Length -eq 0 -or $line.StartsWith("#")) {
        return
    }
    $splitIndex = $line.IndexOf("=")
    if ($splitIndex -lt 1) {
        return
    }
    $name = $line.Substring(0, $splitIndex).Trim()
    $value = $line.Substring($splitIndex + 1).Trim()
    if ($value.Length -ge 2) {
        $isDoubleQuoted = $value.StartsWith('"') -and $value.EndsWith('"')
        $isSingleQuoted = $value.StartsWith("'") -and $value.EndsWith("'")
        if ($isDoubleQuoted -or $isSingleQuoted) {
            $value = $value.Substring(1, $value.Length - 2)
        }
    }
    [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
}

# Optional wrapper for Windows PowerShell 5.1 and newer.
& (Join-Path $PSScriptRoot 'Start.cmd') @args
exit $LASTEXITCODE

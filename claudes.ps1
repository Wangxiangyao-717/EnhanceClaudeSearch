$ErrorActionPreference = 'Stop'
$ScriptRoot = $PSScriptRoot
$ScriptPath = Join-Path $ScriptRoot 'src\app.py'

& python $ScriptPath @args
exit $LASTEXITCODE

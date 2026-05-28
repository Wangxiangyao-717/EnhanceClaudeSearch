$ErrorActionPreference = 'Stop'
$ScriptRoot = $PSScriptRoot
$ScriptPath = Join-Path $ScriptRoot 'src\session_search.py'

& python $ScriptPath @args
exit $LASTEXITCODE

$ErrorActionPreference = "Continue"
$resolvedDir = $PSScriptRoot

$currentPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $currentPath) { $currentPath = '' }

$alreadyPresent = $false
foreach ($entry in $currentPath.Split(';')) {
    if ($entry.Trim().Trim('"').TrimEnd('\') -eq $resolvedDir.TrimEnd('\')) {
        $alreadyPresent = $true
        break
    }
}

if ($alreadyPresent) {
    Write-Host "Already in PATH: $resolvedDir" -ForegroundColor Yellow
} else {
    if ($currentPath.Trim().Length -gt 0) {
        $newPath = $currentPath.TrimEnd(';') + ';' + $resolvedDir
    } else {
        $newPath = $resolvedDir
    }
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    Write-Host "Added to PATH: $resolvedDir" -ForegroundColor Green
    Write-Host "Close and reopen your terminal, then try: csch" -ForegroundColor Gray
}

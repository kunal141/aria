$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$StateFile = Join-Path $RepoRoot ".aria_data\local-employee\employee-processes.json"

if (-not (Test-Path -LiteralPath $StateFile)) {
    Write-Host "ARIA local employee is not running (no process state file)."
    exit 0
}

$state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
$expectedRoots = @(
    @{ Id = [int]$state.frontend_pid; Name = "node" }
    @{ Id = [int]$state.backend_pid; Name = "python" }
    @{ Id = [int]$state.launcher_pid; Name = "powershell" }
)
$rootIds = @()
foreach ($entry in $expectedRoots) {
    $process = Get-Process -Id $entry.Id -ErrorAction SilentlyContinue
    if ($null -ne $process -and $process.ProcessName -eq $entry.Name) {
        $rootIds += $entry.Id
    }
}

$allProcesses = Get-CimInstance Win32_Process |
    Select-Object ProcessId, ParentProcessId
$processIds = @($rootIds)
$frontier = @($rootIds)
while ($frontier.Count -gt 0) {
    $children = @(
        $allProcesses |
            Where-Object { $frontier -contains [int]$_.ParentProcessId } |
            ForEach-Object { [int]$_.ProcessId }
    )
    $children = @($children | Where-Object { $processIds -notcontains $_ })
    if ($children.Count -eq 0) { break }
    $processIds += $children
    $frontier = $children
}

foreach ($processId in @($processIds | Select-Object -Unique | Sort-Object -Descending)) {
    if ($processId -ne $PID) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
Write-Host "ARIA local employee stopped."

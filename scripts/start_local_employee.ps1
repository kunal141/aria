param(
    [ValidateSet("chat", "web")]
    [string]$Mode = "chat",
    [string]$Model = "gemma4:latest",
    [switch]$SkipFitness
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $RepoRoot "apps\backend"
$Frontend = Join-Path $RepoRoot "apps\frontend"
$DataRoot = Join-Path $RepoRoot ".aria_data\local-employee"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Vite = Join-Path $Frontend "node_modules\vite\bin\vite.js"
$StateFile = Join-Path $DataRoot "employee-processes.json"

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw "Ollama is required. Install it and pull the configured local model."
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required to run the ARIA backend."
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "ARIA's virtual environment is missing. Run: uv sync --all-groups"
}
& ollama show $Model *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Model '$Model' is unavailable. Run: ollama pull $Model"
}

New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
$env:PYTHONUTF8 = "1"
$env:PYTHON_DOTENV_DISABLED = "1"
$env:LANGCHAIN_API_KEY = ""
$env:LANGSMITH_API_KEY = ""
$env:LANGCHAIN_TRACING_V2 = "false"
$env:ARIA_DATA_DIR = $DataRoot
$env:ARIA_LEDGER_V2_PATH = Join-Path $DataRoot "work_ledger_v2.jsonl"
$env:ARIA_EXECUTION_MODE = "local_ollama"
$env:LLM_PROVIDER = "ollama"
$env:LOCAL_LLM_PROVIDER = "ollama"
$env:LLM_MODEL = $Model
$env:OLLAMA_HOST = "http://127.0.0.1:11434"
$env:CONNECTOR_MODE = "fixtures"
$env:ARIA_CONNECTOR_MODE = "fixtures"
$env:ARIA_LIVE_EXECUTION = "false"

if (-not $SkipFitness) {
    Push-Location $Backend
    try {
        & $Python -m aria.llm.check --fitness
        if ($LASTEXITCODE -ne 0) { throw "The local model failed ARIA's fitness gate." }
    } finally {
        Pop-Location
    }
}

if ($Mode -eq "chat") {
    Set-Location $Backend
    & $Python -m aria.chat --llm
    exit $LASTEXITCODE
}

$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:8000"
$backendProcess = $null
$frontendProcess = $null
try {
    $backendProcess = Start-Process -FilePath $Python -WorkingDirectory $Backend `
        -ArgumentList @(
            "-m", "uvicorn", "aria.api.staging:build_staging_app",
            "--factory", "--host", "127.0.0.1", "--port", "8000", "--no-access-log"
        ) -WindowStyle Hidden -PassThru
    $quotedVite = '"' + $Vite + '"'
    $frontendProcess = Start-Process -FilePath "node" -WorkingDirectory $Frontend `
        -ArgumentList @($quotedVite, "--host", "127.0.0.1", "--port", "5173") `
        -WindowStyle Hidden -PassThru

    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $ready = Invoke-RestMethod "http://127.0.0.1:8000/ready" -TimeoutSec 2
            if ($ready.status -eq "ready") { break }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    if ($ready.status -ne "ready" -or $backendProcess.HasExited) {
        throw "ARIA backend did not become ready."
    }
    $frontendReady = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if ($frontendProcess.HasExited) { break }
        try {
            $front = Invoke-WebRequest "http://127.0.0.1:5173" -UseBasicParsing -TimeoutSec 2
            if ($front.StatusCode -eq 200) { $frontendReady = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $frontendReady) { throw "ARIA frontend did not become ready." }
    @{
        launcher_pid = $PID
        backend_pid = $backendProcess.Id
        frontend_pid = $frontendProcess.Id
        url = "http://127.0.0.1:5173"
        execution_mode = "local_ollama"
        model = $Model
    } | ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding UTF8
    Write-Host "ARIA local employee is ready: http://127.0.0.1:5173"
    Write-Host "Press Ctrl+C here to stop both services."
    Start-Process "http://127.0.0.1:5173"
    while (-not $backendProcess.HasExited -and -not $frontendProcess.HasExited) {
        Start-Sleep -Seconds 1
    }
} finally {
    foreach ($process in @($frontendProcess, $backendProcess)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
        }
    }
    Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
}

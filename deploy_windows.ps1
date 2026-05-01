# wxarticle Deploy Script - Windows Server (宝塔面板)
# Run in PowerShell as Administrator
# Fresh install: .\deploy_windows.ps1
# Update only:   .\deploy_windows.ps1 -Update

param([switch]$Update)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"
$ProjectDir = "C:\wxarticle"
$RepoUrl = "https://github.com/iamzhangg/wxarticle.git"

Write-Host "=====================================" -ForegroundColor Cyan
if ($Update) {
    Write-Host "  wxarticle Update" -ForegroundColor Cyan
} else {
    Write-Host "  wxarticle Deploy" -ForegroundColor Cyan
}
Write-Host "=====================================" -ForegroundColor Cyan

# ============ Step 1: Check Git ============
Write-Host "`n[1/6] Checking Git..." -ForegroundColor Yellow
try { git --version | Out-Null; Write-Host "  Git OK" -ForegroundColor Green }
catch {
    Write-Host "  Installing Git..." -ForegroundColor Yellow
    $g = "$env:TEMP\git-install.exe"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest "https://github.com/git-for-windows/git/releases/download/v2.49.0.windows.1/Git-2.49.0-64-bit.exe" -OutFile $g -UseBasicParsing
    Start-Process $g -ArgumentList "/VERYSILENT /NORESTART /SP-" -Wait
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    Write-Host "  Git installed" -ForegroundColor Green
}

# ============ Step 2: Check Python ============
Write-Host "`n[2/6] Checking Python..." -ForegroundColor Yellow
$pyCmd = $null
if (Test-Path "$ProjectDir\venv\Scripts\python.exe") {
    $pyCmd = "$ProjectDir\venv\Scripts\python.exe"
    Write-Host "  Using venv Python" -ForegroundColor Green
} else {
    $pyVer = python --version 2>&1
    if ($pyVer -match "3\.(\d+)") {
        $minor = [int]$Matches[1]
        if ($minor -lt 9) {
            Write-Host "  Python 3.$minor too old, installing 3.11..." -ForegroundColor Yellow
            $p = "$env:TEMP\python-install.exe"
            Invoke-WebRequest "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $p -UseBasicParsing
            Start-Process $p -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        }
    }
    $pyCmd = "python"
    Write-Host "  Using system Python" -ForegroundColor Green
}

# ============ Step 3: Get/Update Code ============
Write-Host "`n[3/6] Code..." -ForegroundColor Yellow
if ($Update -and (Test-Path "$ProjectDir\.git")) {
    Set-Location $ProjectDir
    Write-Host "  Stopping service..." -ForegroundColor Yellow
    Stop-Process -Name "python" -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Write-Host "  git pull..." -ForegroundColor Yellow
    git pull origin master 2>&1 | Write-Host
    Write-Host "  Code updated" -ForegroundColor Green
} elseif (Test-Path $ProjectDir) {
    Write-Host "  Backing up old .env..." -ForegroundColor Yellow
    $oldEnv = $null
    if (Test-Path "$ProjectDir\.env") { $oldEnv = Get-Content "$ProjectDir\.env" -Raw }
    Write-Host "  Removing old project..." -ForegroundColor Yellow
    Remove-Item $ProjectDir -Recurse -Force
    Write-Host "  Cloning..." -ForegroundColor Yellow
    git clone $RepoUrl $ProjectDir 2>&1 | Write-Host
    Set-Location $ProjectDir
    if ($oldEnv) {
        Write-Host "  Restoring .env..." -ForegroundColor Yellow
        Set-Content -Path "$ProjectDir\.env" -Value $oldEnv -Encoding ASCII
    }
    Write-Host "  Fresh clone done" -ForegroundColor Green
} else {
    Write-Host "  Cloning..." -ForegroundColor Yellow
    git clone $RepoUrl $ProjectDir 2>&1 | Write-Host
    Set-Location $ProjectDir
    Write-Host "  Clone done" -ForegroundColor Green
}

# ============ Step 4: Venv + Dependencies ============
Write-Host "`n[4/6] Installing dependencies..." -ForegroundColor Yellow
if (-not (Test-Path "$ProjectDir\venv\Scripts\python.exe")) {
    & $pyCmd -m venv "$ProjectDir\venv"
    Write-Host "  Venv created" -ForegroundColor Green
}
$pip = "$ProjectDir\venv\Scripts\pip.exe"
& $pip install -r "$ProjectDir\requirements.txt" -q 2>&1 | Select-Object -Last 5 | Write-Host
Write-Host "  Dependencies installed" -ForegroundColor Green

# ============ Step 5: .env config ============
Write-Host "`n[5/6] Configuring .env..." -ForegroundColor Yellow
if (-not (Test-Path "$ProjectDir\.env")) {
    Copy-Item "$ProjectDir\.env.example" "$ProjectDir\.env"
    Write-Host "  Created .env from .env.example" -ForegroundColor Yellow
    Write-Host "  Please edit C:\wxarticle\.env and fill in your API keys:" -ForegroundColor White
    Write-Host "    SILICONFLOW_API_KEY=  (required)" -ForegroundColor White
    Write-Host "    PEXELS_API_KEY=       (optional)" -ForegroundColor White
} else {
    Write-Host "  .env exists, skipping" -ForegroundColor Green
}

# ============ Step 6: Setup Auto-start + Start Service ============
Write-Host "`n[6/6] Setting up service..." -ForegroundColor Yellow

# Stop existing process on port 8080
$existing = netstat -aon | Select-String ":8080" | Select-String "LISTENING"
if ($existing) {
    $existingPid = ($existing -split "\s+")[-1]
    Write-Host "  Stopping old process (PID: $existingPid)..." -ForegroundColor Yellow
    Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# Create scheduled task for auto-start (survives reboot)
$taskName = "wxarticle"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute "$ProjectDir\venv\Scripts\python.exe" -Argument "start_web.py" -WorkingDirectory $ProjectDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Host "  Auto-start task created" -ForegroundColor Green

# Start the service now
$proc = Start-Process -FilePath "$ProjectDir\venv\Scripts\python.exe" -ArgumentList "start_web.py" -WorkingDirectory $ProjectDir -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 5

if (-not $proc.HasExited) {
    Write-Host "`n=====================================" -ForegroundColor Green
    Write-Host "  DEPLOY SUCCESS!" -ForegroundColor Green
    Write-Host "=====================================" -ForegroundColor Green
    Write-Host "  Local:  http://localhost:8080" -ForegroundColor White
    Write-Host "  PID:    $($proc.Id)" -ForegroundColor White
    Write-Host "  Logs:   $ProjectDir\generate.log" -ForegroundColor Gray
    Write-Host "  Restart:.\restart.bat" -ForegroundColor Gray
    Write-Host "" -ForegroundColor Gray
    Write-Host "  Next:   Edit C:\wxarticle\.env and restart" -ForegroundColor Yellow
} else {
    Write-Host "`n  [WARN] Service exited immediately. Check:" -ForegroundColor Red
    Write-Host "    1. .env SILICONFLOW_API_KEY is set" -ForegroundColor Red
    Write-Host "    2. Run manually: $ProjectDir\venv\Scripts\python.exe $ProjectDir\start_web.py" -ForegroundColor Red
}

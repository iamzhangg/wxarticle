# wxarticle Deploy Script - Windows Server
# Run in PowerShell as Administrator
# Fresh install: .\deploy_windows.ps1
# Update only:   .\deploy_windows.ps1 -Update

param([switch]$Update)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"
$ProjectDir = "C:\wxarticle"
$RepoUrl = "https://github.com/iamzhangg/wxarticle.git"
$PipIndexUrl = "https://pypi.tuna.tsinghua.edu.cn/simple"
$ServiceHost = "127.0.0.1"
$ServicePort = 8080

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
& $pip install -r "$ProjectDir\requirements.txt" -i $PipIndexUrl -q 2>&1 | Select-Object -Last 5 | Write-Host
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

# Keep the Python service local-only. Use BaoTa/Nginx reverse proxy for public access.
[System.Environment]::SetEnvironmentVariable("HOST", $ServiceHost, "Machine")
[System.Environment]::SetEnvironmentVariable("PORT", "$ServicePort", "Machine")
$env:HOST = $ServiceHost
$env:PORT = "$ServicePort"

# Stop existing process on service port
$existing = netstat -aon | Select-String ":$ServicePort" | Select-String "LISTENING"
if ($existing) {
    $existingPid = ($existing -split "\s+")[-1]
    Write-Host "  Stopping old process (PID: $existingPid)..." -ForegroundColor Yellow
    Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# Create scheduled task for auto-start (survives reboot)
$taskName = "wxarticle"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
$taskCmd = "Set-Location '$ProjectDir'; `$env:HOST='$ServiceHost'; `$env:PORT='$ServicePort'; & '$ProjectDir\venv\Scripts\python.exe' 'start_web.py'"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$taskCmd`"" -WorkingDirectory $ProjectDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Host "  Auto-start task created" -ForegroundColor Green

# Start the service now
$procCmd = "Set-Location '$ProjectDir'; `$env:HOST='$ServiceHost'; `$env:PORT='$ServicePort'; & '$ProjectDir\venv\Scripts\python.exe' 'start_web.py'"
$proc = Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$procCmd`"" -WorkingDirectory $ProjectDir -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 5

if (-not $proc.HasExited) {
    Write-Host "`n=====================================" -ForegroundColor Green
    Write-Host "  DEPLOY SUCCESS!" -ForegroundColor Green
    Write-Host "=====================================" -ForegroundColor Green
    Write-Host "  Local:  http://localhost:$ServicePort" -ForegroundColor White
    Write-Host "  PID:    $($proc.Id)" -ForegroundColor White
    Write-Host "  Logs:   $ProjectDir\generate.log" -ForegroundColor Gray
    Write-Host "  Restart:.\restart.bat" -ForegroundColor Gray
    Write-Host "" -ForegroundColor Gray
    Write-Host "  Next:   Edit C:\wxarticle\.env and restart" -ForegroundColor Yellow
    Write-Host "  BaoTa:  Reverse proxy public site to http://127.0.0.1:$ServicePort" -ForegroundColor Yellow
    Write-Host "          Add auth/firewall rules before exposing it to the internet." -ForegroundColor Yellow
} else {
    Write-Host "`n  [WARN] Service exited immediately. Check:" -ForegroundColor Red
    Write-Host "    1. .env SILICONFLOW_API_KEY is set" -ForegroundColor Red
    Write-Host "    2. Run manually: $ProjectDir\venv\Scripts\python.exe $ProjectDir\start_web.py" -ForegroundColor Red
}

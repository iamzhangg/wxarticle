# wxarticle deploy script - run on server PowerShell
# Copy all and paste into PowerShell

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "  wxarticle Deploy" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan

# 1. Check/Install Git
Write-Host "`n[1/7] Checking Git..." -ForegroundColor Yellow
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

# 2. Check Python
Write-Host "`n[2/7] Checking Python..." -ForegroundColor Yellow
$pyVer = python --version 2>&1
Write-Host "  Current: $pyVer" -ForegroundColor White
if ($pyVer -match "3\.(\d+)") {
    $minor = [int]$Matches[1]
    if ($minor -lt 9) {
        Write-Host "  Python 3.$minor is old, installing 3.11..." -ForegroundColor Yellow
        $p = "$env:TEMP\python-install.exe"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $p -UseBasicParsing
        Start-Process $p -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        Write-Host "  Python 3.11 installed" -ForegroundColor Green
    }
}

# 3. Clone project
Write-Host "`n[3/7] Cloning project..." -ForegroundColor Yellow
$dir = "C:\wxarticle"
if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
git clone https://github.com/iamzhangg/wxarticle.git $dir 2>&1 | Write-Host
Set-Location $dir
Write-Host "  Clone done" -ForegroundColor Green

# 4. Create venv
Write-Host "`n[4/7] Creating venv..." -ForegroundColor Yellow
python -m venv venv
Write-Host "  Venv created" -ForegroundColor Green

# 5. Install deps
Write-Host "`n[5/7] Installing dependencies..." -ForegroundColor Yellow
.\venv\Scripts\python.exe -m pip install --upgrade pip 2>&1 | Select-Object -Last 2 | Write-Host
.\venv\Scripts\pip.exe install python-dotenv requests PyYAML beautifulsoup4 fastapi uvicorn 2>&1 | Select-Object -Last 3 | Write-Host
Write-Host "  Dependencies installed" -ForegroundColor Green

# 6. Config .env
Write-Host "`n[6/7] Configuring .env..." -ForegroundColor Yellow
$sfKey = Read-Host "  Paste SILICONFLOW_API_KEY"
$pxKey = Read-Host "  Paste PEXELS_API_KEY (or press Enter to skip)"
$ghToken = Read-Host "  Paste DATA_GIT_TOKEN (or press Enter to skip)"

$envLines = @()
$envLines += "SILICONFLOW_API_KEY=$sfKey"
$envLines += "PEXELS_API_KEY=$pxKey"
$envLines += "IMAGE_SOURCE=stock"
$envLines += "MODEL_NAME=Qwen/Qwen3-235B-A22B-Instruct-2507"
$envLines += "DATA_GIT_REPO=https://github.com/iamzhangg/wxarticle"
$envLines += "DATA_GIT_TOKEN=$ghToken"
$envLines += "DATA_GIT_BRANCH=data"
$envLines | Set-Content -Path ".env" -Encoding ASCII
Write-Host "  .env configured" -ForegroundColor Green

# 7. Start service
Write-Host "`n[7/7] Starting service..." -ForegroundColor Yellow

# Create start.bat
$batContent = "@echo off`r`ncd /d C:\wxarticle`r`nC:\wxarticle\venv\Scripts\python.exe start_web.py`r`npause"
Set-Content -Path "C:\wxarticle\start.bat" -Value $batContent -Encoding ASCII

# Create scheduled task for auto-start
Unregister-ScheduledTask -TaskName "wxarticle" -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute "C:\wxarticle\venv\Scripts\python.exe" -Argument "start_web.py" -WorkingDirectory "C:\wxarticle"
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "wxarticle" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -User "SYSTEM" -Force | Out-Null
Write-Host "  Auto-start task created" -ForegroundColor Green

# Start now
$proc = Start-Process -FilePath "C:\wxarticle\venv\Scripts\python.exe" -ArgumentList "start_web.py" -WorkingDirectory "C:\wxarticle" -PassThru
Start-Sleep -Seconds 5

if (-not $proc.HasExited) {
    Write-Host "`n=====================================" -ForegroundColor Green
    Write-Host "  DEPLOY SUCCESS!" -ForegroundColor Green
    Write-Host "=====================================" -ForegroundColor Green
    Write-Host "  Local:  http://localhost:8080" -ForegroundColor White
    Write-Host "  Public: http://123.207.199.142:8080" -ForegroundColor White
    Write-Host "  PID:    $($proc.Id)" -ForegroundColor White
    Write-Host "  Stop:   Stop-Process -Id $($proc.Id)" -ForegroundColor Gray
} else {
    Write-Host "`nService failed to start" -ForegroundColor Red
}

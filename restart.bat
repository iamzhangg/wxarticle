@echo off
chcp 65001 >nul
echo ================================
echo  wxarticle 服务重启脚本
echo ================================
echo.

:: 查找并终止旧的 wxarticle 进程
echo [1/3] 停止旧服务...
taskkill /F /FI "WINDOWTITLE eq wxarticle*" >nul 2>&1
for /f "tokens=2" %%a in ('tasklist ^| findstr /I "python.*start_web"') do (
    taskkill /F /PID %%a >nul 2>&1
)
:: 也通过端口查找进程
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8080 ^| findstr LISTENING') do (
    echo   终止进程 PID: %%a
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

:: 安装新依赖
echo [2/3] 安装依赖...
pip install -r requirements.txt -q 2>nul
if exist venv\Scripts\pip.exe (
    venv\Scripts\pip.exe install -r requirements.txt -q 2>nul
)

:: 启动新服务
echo [3/3] 启动新服务...
if exist venv\Scripts\python.exe (
    start "wxarticle" venv\Scripts\python.exe start_web.py
) else (
    start "wxarticle" python start_web.py
)

echo.
echo ================================
echo  重启完成！
echo  访问: http://localhost:8080
echo ================================
timeout /t 5

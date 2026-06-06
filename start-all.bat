@echo off
chcp 65001 > nul
echo.
echo 🚀 启动竞品情报系统...
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到 Python，请先安装或激活虚拟环境
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo ✓ %PYTHON_VERSION%

REM 检查 Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到 Node.js，请先安装
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('node --version') do set NODE_VERSION=%%i
echo ✓ Node.js %NODE_VERSION%

echo.
echo 启动后端... (http://localhost:8000)
start "AI员工 - 后端" cmd /k "cd /d %~dp0 && python -m src.main --schedule"

echo 等待后端启动...
timeout /t 3 /nobreak

echo 启动前端... (http://localhost:3000)
start "AI员工 - 前端" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo ✓ 系统已启动！
echo   后端: http://localhost:8000
echo   前端: http://localhost:3000
echo.
echo 关闭窗口可停止进程
pause

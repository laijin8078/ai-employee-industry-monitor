# 同时启动后端和前端
Write-Host "🚀 启动竞品情报系统..." -ForegroundColor Green
Write-Host ""

# 检查 Python 环境
$pythonCheck = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 未找到 Python，请先安装或激活虚拟环境" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Python: $pythonCheck" -ForegroundColor Green

# 检查 Node.js
$nodeCheck = node --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 未找到 Node.js，请先安装" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Node.js: $nodeCheck" -ForegroundColor Green

Write-Host ""
Write-Host "启动API服务... (http://localhost:8001)" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot'; python -m uvicorn src.api_server:app --host 0.0.0.0 --port 8001 --reload"

Write-Host "等待后端启动..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

Write-Host "启动前端... (http://localhost:3000)" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot/frontend'; npm.cmd run dev"

Write-Host ""
Write-Host "✓ 系统已启动！" -ForegroundColor Green
Write-Host "  API: http://localhost:8001" -ForegroundColor Green
Write-Host "  前端: http://localhost:3000" -ForegroundColor Green
Write-Host ""
Write-Host "关闭此窗口可停止所有进程" -ForegroundColor Yellow

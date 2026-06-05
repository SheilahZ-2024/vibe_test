# 本地开发环境一键脚本（Windows PowerShell）
# 用法：在项目根目录执行  .\scripts\setup.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> 复制 .env" -ForegroundColor Cyan
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

Write-Host "==> 前端 npm install" -ForegroundColor Cyan
Set-Location apps\web
npm install
Set-Location $Root

Write-Host "==> 后端 Python venv (3.12)" -ForegroundColor Cyan
$py312 = @(
  "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
  "py -3.12"
) | ForEach-Object { if ($_ -like "py*") { & py -3.12 -c "import sys; print(sys.executable)" 2>$null } elseif (Test-Path $_) { $_ } } | Select-Object -First 1

if (-not $py312) {
  Write-Host "未找到 Python 3.12，请运行: winget install Python.Python.3.12" -ForegroundColor Red
  exit 1
}

Set-Location apps\api
if (Test-Path .venv) { Remove-Item -Recurse -Force .venv }
& $py312 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
Set-Location $Root

Write-Host "==> 生成 Mock 数据 SQL" -ForegroundColor Cyan
if (Test-Path apps\api\.venv\Scripts\python.exe) {
  & apps\api\.venv\Scripts\python.exe scripts\generate_mock_data.py
} else {
  python scripts\generate_mock_data.py
}

Write-Host ""
Write-Host "环境就绪。下一步：" -ForegroundColor Green
Write-Host "  1. 启动 Docker Desktop（首次需登录/启用 WSL2）"
Write-Host "  2. docker compose up --build"
Write-Host "  3. 浏览器打开 http://localhost:5173"
Write-Host ""
Write-Host "本地开发（不用 Docker 跑前后端时）："
Write-Host "  docker compose up postgres redis -d"
Write-Host "  apps\api\.venv\Scripts\uvicorn app.main:app --reload --app-dir apps\api\app  # 需在 apps/api 下"
Write-Host "  cd apps\web && npm run dev"

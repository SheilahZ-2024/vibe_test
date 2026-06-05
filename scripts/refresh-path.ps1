# 刷新当前 PowerShell 会话的 PATH（安装 Git/Docker 后若命令找不到，先执行此脚本）
# 用法: . .\scripts\refresh-path.ps1

$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + `
  [System.Environment]::GetEnvironmentVariable("Path", "User")

Write-Host "PATH 已刷新。验证：" -ForegroundColor Green
git --version
docker --version

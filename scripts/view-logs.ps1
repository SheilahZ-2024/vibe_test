# 在本机 PowerShell 查看阿里云容器日志（避免使用 bash 的 &&）
param(
    [string]$ServerIp = "47.99.155.107",
    [int]$Tail = 80
)

$cmd = "cd /root/smart-assistant; /usr/local/bin/docker-compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail $Tail api web"
Write-Host "连接 $ServerIp 查看日志 …" -ForegroundColor Cyan
ssh root@$ServerIp $cmd

# 从本机 Windows 通过 SSH 部署到阿里云（Workbench 卡住时用）
# 用法：.\scripts\deploy-from-local.ps1
# 会提示输入 root 密码（换 Linux 时在控制台设的）

param(
    [string]$ServerIp = "47.99.155.107",
    [string]$RootPassword = ""
)

$ErrorActionPreference = "Stop"

if (-not $RootPassword) {
    $secure = Read-Host "请输入服务器 root 密码" -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $RootPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

$llmKey = ""
$envFile = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
if (Test-Path $envFile) {
    $m = Select-String -Path $envFile -Pattern '^LLM_API_KEY=(.+)$' | Select-Object -First 1
    if ($m) { $llmKey = $m.Matches.Groups[1].Value.Trim() }
}

Write-Host "==> 测试 SSH 连接 $ServerIp ..." -ForegroundColor Cyan

$remoteScript = @"
set -e
export PUBLIC_IP=$ServerIp
export LLM_API_KEY='$llmKey'
export WEB_PORT=5173
if [ -d /root/smart-assistant/.git ]; then
  cd /root/smart-assistant && git pull
else
  rm -rf /root/smart-assistant
  git clone https://github.com/SheilahZ-2024/vibe_test.git /root/smart-assistant
  cd /root/smart-assistant
fi
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable docker && systemctl start docker
fi
command -v git >/dev/null || (yum install -y git 2>/dev/null || apt-get update && apt-get install -y git)
bash scripts/deploy-aliyun.sh
curl -fsS http://127.0.0.1:5173/health || true
echo DEPLOY_OK
"@

# 优先 WSL + sshpass
$wsl = Get-Command wsl -ErrorAction SilentlyContinue
if ($wsl) {
    $bashScript = Join-Path $env:TEMP "remote-deploy.sh"
    Set-Content -Path $bashScript -Value $remoteScript -Encoding UTF8
    wsl -e bash -lc "command -v sshpass >/dev/null 2>&1 || sudo apt-get update -qq && sudo apt-get install -y -qq sshpass"
    wsl -e bash -lc "sshpass -p '$($RootPassword.Replace("'","'\''"))' scp -o StrictHostKeyChecking=no '$($bashScript -replace '\\','/')' root@${ServerIp}:/tmp/remote-deploy.sh"
    wsl -e bash -lc "sshpass -p '$($RootPassword.Replace("'","'\''"))' ssh -o StrictHostKeyChecking=no root@${ServerIp} 'bash /tmp/remote-deploy.sh'"
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "部署完成！访问: http://${ServerIp}:5173" -ForegroundColor Green
        exit 0
    }
    Write-Host "WSL 部署失败，尝试 plink ..." -ForegroundColor Yellow
}

$plink = Get-Command plink -ErrorAction SilentlyContinue
if ($plink) {
    & plink -batch -ssh root@$ServerIp -pw $RootPassword $remoteScript
    Write-Host "部署完成！访问: http://${ServerIp}:5173" -ForegroundColor Green
    exit 0
}

Write-Host @"

无法自动传密码（需要 WSL+sshpass 或 PuTTY plink）。

请在本机 PowerShell 手动执行（会提示输入密码）：

  ssh root@$ServerIp

登录后粘贴：

export PUBLIC_IP=$ServerIp
export LLM_API_KEY=$llmKey
curl -fsSL https://raw.githubusercontent.com/SheilahZ-2024/vibe_test/main/scripts/workbench-bootstrap.sh -o /tmp/bootstrap.sh
bash /tmp/bootstrap.sh

"@ -ForegroundColor Yellow

#!/usr/bin/env bash
# 在阿里云 Workbench 远程终端里整段粘贴执行（无需本机 SSH）
# 可选：export LLM_API_KEY=你的密钥 后再执行

set -euo pipefail

PUBLIC_IP="${PUBLIC_IP:-47.99.155.107}"
WEB_PORT="${WEB_PORT:-5173}"
REPO="${REPO:-https://github.com/SheilahZ-2024/vibe_test.git}"
APP_DIR="${APP_DIR:-/root/smart-assistant}"

echo "==> 安装 Git / Docker"
if command -v apt-get &>/dev/null; then
  apt-get update -qq
  apt-get install -y git curl
elif command -v yum &>/dev/null; then
  yum install -y git curl
fi

if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh 2>/dev/null || true
  if ! command -v docker &>/dev/null; then
    dnf install -y docker docker-compose-plugin 2>/dev/null || yum install -y docker docker-compose-plugin 2>/dev/null || yum install -y docker
  fi
  systemctl enable docker
  systemctl start docker
fi

echo "==> 拉取代码"
if [[ -d "$APP_DIR/.git" ]]; then
  cd "$APP_DIR" && git pull
else
  rm -rf "$APP_DIR"
  git clone "$REPO" "$APP_DIR"
  cd "$APP_DIR"
fi

export PUBLIC_IP WEB_PORT
export LLM_API_KEY="${LLM_API_KEY:-}"
bash scripts/deploy-aliyun.sh

echo ""
echo "=========================================="
echo "  Demo 地址: http://${PUBLIC_IP}:${WEB_PORT}"
echo "  若打不开，请在阿里云安全组放行 TCP ${WEB_PORT}"
echo "=========================================="

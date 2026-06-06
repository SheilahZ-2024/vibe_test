#!/usr/bin/env bash
# 阿里云 ECS / 轻量服务器一键部署（Ubuntu 22.04 / Alibaba Cloud Linux 3）
# 用法：curl 下载后在项目根目录执行  bash scripts/deploy-aliyun.sh
# 或 SSH 登录服务器后：git clone ... && cd smart-assistant && bash scripts/deploy-aliyun.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> 检查 Docker"
install_docker() {
  if command -v docker &>/dev/null; then
    return 0
  fi
  echo "    安装 Docker..."
  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-}" in
      alinux|anolis|centos|rhel|fedora|rocky|almalinux)
        if command -v dnf &>/dev/null; then
          dnf install -y docker docker-compose-plugin 2>/dev/null || dnf install -y docker
        else
          yum install -y docker docker-compose-plugin 2>/dev/null || yum install -y docker
        fi
        systemctl enable docker
        systemctl start docker
        return 0
        ;;
      ubuntu|debian)
        apt-get update -qq
        apt-get install -y docker.io docker-compose-plugin 2>/dev/null || apt-get install -y docker.io
        systemctl enable docker
        systemctl start docker
        return 0
        ;;
    esac
  fi
  curl -fsSL https://get.docker.com | sh
  systemctl enable docker
  systemctl start docker
}

install_docker

if ! docker compose version &>/dev/null 2>&1; then
  echo "    安装 Docker Compose 插件..."
  if command -v dnf &>/dev/null; then
    dnf install -y docker-compose-plugin 2>/dev/null || true
  elif command -v yum &>/dev/null; then
    yum install -y docker-compose-plugin 2>/dev/null || true
  elif command -v apt-get &>/dev/null; then
    apt-get update -qq && apt-get install -y docker-compose-plugin 2>/dev/null || true
  fi
fi

if ! docker compose version &>/dev/null 2>&1 && command -v docker-compose &>/dev/null; then
  echo "    使用 docker-compose 命令兼容模式"
  docker() {
    if [[ "$1" == "compose" ]]; then
      shift
      command docker-compose "$@"
    else
      command docker "$@"
    fi
  }
fi

echo "==> 准备 .env"
if [[ ! -f .env ]]; then
  cp .env.example .env
  # 随机数据库密码
  DB_PASS="$(openssl rand -hex 12 2>/dev/null || head -c 24 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 24)"
  sed -i "s/change_me_in_production/${DB_PASS}/g" .env
  sed -i "s/change_me_jwt_or_internal_secret/$(openssl rand -hex 16 2>/dev/null || echo "prod_secret_change_me")/g" .env
  echo "    已生成 .env（随机数据库密码）"
fi

if [[ -n "${LLM_API_KEY:-}" ]]; then
  if grep -q '^LLM_API_KEY=' .env; then
    sed -i "s|^LLM_API_KEY=.*|LLM_API_KEY=${LLM_API_KEY}|" .env
  fi
  echo "    已写入 LLM_API_KEY"
fi

# 若未设置 CORS，尝试写入公网 IP
PUBLIC_IP="${PUBLIC_IP:-}"
if [[ -z "$PUBLIC_IP" ]]; then
  PUBLIC_IP="$(curl -fsSL --max-time 3 http://100.100.100.200/latest/meta-data/eipv4 2>/dev/null || true)"
fi
if [[ -z "$PUBLIC_IP" ]]; then
  PUBLIC_IP="$(curl -fsSL --max-time 3 ifconfig.me 2>/dev/null || true)"
fi
WEB_PORT="${WEB_PORT:-5173}"
if [[ -n "$PUBLIC_IP" ]] && ! grep -q "CORS_ORIGINS=.*${PUBLIC_IP}" .env 2>/dev/null; then
  if grep -q '^CORS_ORIGINS=' .env; then
    sed -i "s|^CORS_ORIGINS=.*|CORS_ORIGINS=http://${PUBLIC_IP}:${WEB_PORT},http://localhost:5173|" .env
  fi
  echo "    CORS 已设为 http://${PUBLIC_IP}:${WEB_PORT}"
fi

export WEB_PORT

echo "==> 构建并启动（生产模式，仅暴露 ${WEB_PORT} 端口）"
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

echo ""
echo "==> 部署完成"
echo "    访问地址: http://${PUBLIC_IP:-你的公网IP}:${WEB_PORT}"
echo "    健康检查: curl http://127.0.0.1:${WEB_PORT}/health"
echo ""
echo "    若外网无法访问，请在阿里云控制台 → 安全组 → 入方向 放行 TCP ${WEB_PORT}"
echo "    查看日志: docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api web"

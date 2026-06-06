# 阿里云部署指南（手动）

将 Demo 部署到阿里云 ECS / 轻量服务器。**请在服务器上自行 SSH 登录后操作**，仓库内不提供自动上传/一键上云脚本。

## 一、服务器要求

| 项目 | 建议 |
|------|------|
| 配置 | 2 核 4G 及以上（2G 可加 swap） |
| 系统 | Ubuntu 22.04 或 Alibaba Cloud Linux 3 |
| 磁盘 | ≥ 40GB |

## 二、控制台

1. 安全组入方向放行 **5173**（或 80，见下文）
2. **不要**对公网开放 5432 / 6379 / 8000

## 三、首次部署

```bash
ssh root@你的公网IP

# 安装 Git、Docker（若未安装）
apt update && apt install -y git
curl -fsSL https://get.docker.com | sh
systemctl enable docker && systemctl start docker

git clone https://github.com/SheilahZ-2024/vibe_test.git smart-assistant
cd smart-assistant

cp .env.example .env
nano .env
```

`.env` 至少修改：

```env
POSTGRES_PASSWORD=强密码
API_SECRET_KEY=随机长字符串
LLM_API_KEY=火山方舟密钥          # 体验真实 AI 时必填
CORS_ORIGINS=http://你的公网IP:5173
VITE_API_BASE_URL=
```

启动：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

API 启动时会自动：schema migrate → 知识库/bootstrap → bulk seed（v5）→ mock 时间对齐。

## 四、验证

```bash
curl -s http://127.0.0.1:5173/health
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

浏览器访问：`http://你的公网IP:5173`

Demo 用户对照见 [DEMO_GUIDE.md](./DEMO_GUIDE.md)。

## 五、更新代码

```bash
cd ~/smart-assistant
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart api
```

## 六、运维

```bash
# 日志
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f web api

# 停止
docker compose -f docker-compose.yml -f docker-compose.prod.yml down

# 重置数据库（清空 Demo 数据）
docker compose -f docker-compose.yml -f docker-compose.prod.yml down -v
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## 七、可选

- **80 端口**：`export WEB_PORT=80` 后重新 `up -d --build`，安全组放行 80
- **2G 内存**：增加 2G swap
- **HTTPS**：需 ICP 备案后自行配置 Nginx/Certbot

# 阿里云部署指南（手动）

将 Demo 部署到阿里云 ECS / 轻量应用服务器。推荐 **本机打包 + scp + SSH** 更新（私有仓库或网络受限时更稳）。

---

## 一、服务器要求

| 项目 | 建议 |
|------|------|
| 配置 | 2 核 4G 及以上（2G 可加 swap） |
| 系统 | Ubuntu 22.04 或 Alibaba Cloud Linux 3 |
| 磁盘 | ≥ 40GB |

## 二、安全组

1. 入方向放行 **5173**（或 80）
2. **不要**对公网开放 5432 / 6379 / 8000

---

## 三、首次部署

### 方式 A：Git（公网可 clone 时）

```bash
ssh root@你的公网IP
apt update && apt install -y git
curl -fsSL https://get.docker.com | sh
systemctl enable docker && systemctl start docker

git clone https://github.com/SheilahZ-2024/vibe_test.git smart-assistant
cd smart-assistant
cp .env.example .env && nano .env
```

### 方式 B：本机 tar 上传（推荐）

见下文 **「日常更新」** 的 PowerShell 命令，首次解压到 `/root/smart-assistant` 后配置 `.env` 即可。

### `.env` 必填项

```env
POSTGRES_PASSWORD=强密码
API_SECRET_KEY=随机长字符串
LLM_API_KEY=火山方舟密钥
CORS_ORIGINS=http://你的公网IP:5173
VITE_API_BASE_URL=
```

### 启动

**Alibaba Cloud Linux** 请用：

```bash
cd /root/smart-assistant
/usr/local/bin/docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Ubuntu 可用 `docker compose`（带空格）。

API 启动时会自动：migrate → 知识库 bootstrap → bulk seed（版本落后时重灌 v6）→ mock 时间对齐。

---

## 四、验证

```bash
curl -s http://127.0.0.1:5173/health
/usr/local/bin/docker-compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

浏览器：`http://你的公网IP:5173`  
Demo 用户见 [DEMO_GUIDE.md](./DEMO_GUIDE.md)。

---

## 五、日常更新（本机 PowerShell）

```powershell
cd C:\Users\15924\Projects\smart-assistant

tar -czf $env:TEMP\smart-assistant.tar.gz `
  --exclude=node_modules --exclude=.venv --exclude=__pycache__ `
  --exclude=.git --exclude=dist --exclude=scripts/vendor .

scp -i $env:USERPROFILE\.ssh\id_aliyun $env:TEMP\smart-assistant.tar.gz root@47.99.155.107:/tmp/
scp -i $env:USERPROFILE\.ssh\id_aliyun .env root@47.99.155.107:/tmp/smart-assistant.env

ssh -i $env:USERPROFILE\.ssh\id_aliyun root@47.99.155.107 @"
rm -rf /root/smart-assistant && mkdir -p /root/smart-assistant &&
tar -xzf /tmp/smart-assistant.tar.gz -C /root/smart-assistant &&
mv /tmp/smart-assistant.env /root/smart-assistant/.env &&
cd /root/smart-assistant &&
/usr/local/bin/docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build api web
"@
```

> 日常更新**不要** `down -v`，除非修改了 `POSTGRES_PASSWORD`。  
> seed 版本升级时，api 重启会自动重灌 mock 数据。

若使用 Git 更新：

```bash
cd ~/smart-assistant && git pull
/usr/local/bin/docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

---

## 六、运维

```bash
# 日志
/usr/local/bin/docker-compose -f docker-compose.yml -f docker-compose.prod.yml logs -f web api

# 停止
/usr/local/bin/docker-compose -f docker-compose.yml -f docker-compose.prod.yml down

# 完全重置（清空数据库卷）
/usr/local/bin/docker-compose -f docker-compose.yml -f docker-compose.prod.yml down -v
/usr/local/bin/docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

---

## 七、可选

- **80 端口**：`export WEB_PORT=80` 后重新 `up -d --build`
- **2G 内存**：增加 2G swap
- **HTTPS**：备案后自行配置 Nginx/Certbot

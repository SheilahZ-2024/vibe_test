# 阿里云部署指南

将「AI 履约服务管家」Demo 部署到阿里云 ECS / 轻量应用服务器，供朋友通过公网访问。

## 一、服务器要求

| 项目 | 建议 |
|------|------|
| 配置 | **2 核 4G** 及以上（2G 内存也能跑，建议加 swap） |
| 系统 | Ubuntu 22.04 或 Alibaba Cloud Linux 3 |
| 带宽 | 轻量 200M 峰值即可 |
| 磁盘 | ≥ 40GB |

## 二、阿里云控制台（必做）

1. **安全组 → 入方向 → 添加规则**
   - 协议：TCP
   - 端口：**5173**（若改用 80，则填 80）
   - 授权对象：`0.0.0.0/0`（Demo 用；正式环境可收窄）

2. **不要**对公网开放 5432（Postgres）、6379（Redis）、8000（API）。生产 compose 已默认不映射这些端口。

3. 记下 **公网 IP**，例如 `47.96.xxx.xxx`。

## 三、SSH 登录服务器

```bash
ssh root@你的公网IP
```

## 四、安装 Git 并拉代码

```bash
# Ubuntu
apt update && apt install -y git

# 阿里云 Linux
# yum install -y git

git clone https://github.com/SheilahZ-2024/vibe_test.git smart-assistant
cd smart-assistant
```

若仓库为私有，需配置 SSH Key 或 Personal Access Token。

## 五、配置环境变量

```bash
cp .env.example .env
nano .env   # 或 vi .env
```

**至少修改：**

```env
POSTGRES_PASSWORD=请改成强密码（与 DATABASE_URL 中一致）
API_SECRET_KEY=随机长字符串

# 朋友要体验真实 AI 回复时必填
LLM_API_KEY=你的火山方舟密钥
LLM_FALLBACK_TO_MOCK=true

# 改成你的公网访问地址
CORS_ORIGINS=http://47.96.xxx.xxx:5173

# 留空即可，前端走同源 /api 代理
VITE_API_BASE_URL=
```

无 `LLM_API_KEY` 时系统自动 Mock，仍可演示完整链路。

## 六、一键部署

```bash
chmod +x scripts/deploy-aliyun.sh
bash scripts/deploy-aliyun.sh
```

或手动：

```bash
# 安装 Docker（若未安装）
curl -fsSL https://get.docker.com | sh
systemctl enable docker && systemctl start docker

# 启动（生产模式）
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## 七、验证

在服务器上：

```bash
curl http://127.0.0.1:5173/health
# 应返回 {"status":"ok",...}

docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
# 四个服务均 healthy / up
```

在本地浏览器打开：

```text
http://你的公网IP:5173
```

## 八、常用运维命令

```bash
cd ~/smart-assistant

# 查看日志
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f web api

# 更新代码后重新部署
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# 停止
docker compose -f docker-compose.yml -f docker-compose.prod.yml down

# 重置数据库（会清空 Demo 数据）
docker compose -f docker-compose.yml -f docker-compose.prod.yml down -v
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## 九、可选优化

### 使用 80 端口（链接更简洁）

```bash
export WEB_PORT=80
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

安全组放行 **80**，访问 `http://公网IP/`。

### 2G 内存加 swap

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

### 绑定域名 + HTTPS

国内域名需 **ICP 备案**。备案完成后可用 Nginx/Certbot 或阿里云 CDN 配置 HTTPS。Demo 阶段直接用 `IP:5173` 即可。

## 十、发给朋友的链接

```text
http://你的公网IP:5173
```

可附带几句体验话术，例如：「扫不出来」「我要退款」「店关门了」。

# 抖音生活服务 AI履约服务管家

面向抖音生活服务 C 端用户的 P0 Demo。它不是智能客服、AI 问答机器人、FAQ 系统或帮助中心，而是嵌入生活服务旅程的 **AI履约服务管家**。

核心目标：帮助用户成功完成一次生活服务消费履约。

## 核心能力

- 展示履约旅程：发现团购、购买、预约、到店、核销、消费、售后。
- 查询生活服务订单：团购套餐、电影票、预约服务。
- 查看团购券：券码、有效期、核销状态、使用规则。
- 诊断核销失败：查询订单、团购券、门店，给出可执行解决方案。
- 解释优惠券：门槛、类目、叠加限制、不可用原因。
- 售后退款：规则判断、创建退款申请、展示处理进度。
- 门店履约：营业时间、地址、电话、预约/改约能力。
- 转人工：创建服务工单并同步上下文。

## 技术架构

```text
apps/web          React + Vite + Tailwind，移动端履约服务管家体验
apps/api          FastAPI，SSE 流式对话、业务工具、LLM 编排
deploy/init-db    PostgreSQL 领域 schema 与生活服务种子数据
docker-compose    postgres + redis + api + web(nginx)
```

## 快速开始

### 依赖

已在本机准备：

- Git 2.54
- Docker Desktop 4.76（首次需要手动启动并完成 WSL2/协议向导）
- Node.js 22
- Python 3.12（后端 venv 使用 3.12）

如果终端找不到 `git` 或 `docker`：

```powershell
cd C:\Users\15924\Projects\smart-assistant
. .\scripts\refresh-path.ps1
```

### 初始化依赖

```powershell
cd C:\Users\15924\Projects\smart-assistant
.\scripts\setup.ps1
```

### 启动全栈服务

首次请先打开 Docker Desktop，确认状态为 Running。

```powershell
cd C:\Users\15924\Projects\smart-assistant
copy .env.example .env
docker compose up --build
```

如果之前启动过旧版 schema，请先重置本地数据库卷：

```powershell
docker compose down -v
docker compose up --build
```

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:5173 |
| API 文档 | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/health |

无 `OPENAI_API_KEY` 时，系统自动使用内置 Mock 模型，仍可完整演示业务链路。

### 接入豆包（火山方舟）

在 `.env` 中配置：

```env
OPENAI_API_KEY=你的方舟API密钥
OPENAI_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
OPENAI_MODEL=doubao-seed-1-8-251228
OPENAI_TEMPERATURE=0.3
OPENAI_MAX_TOKENS=1200
```

注意：`OPENAI_MODEL` 填写豆包官网模型 ID（如 `doubao-seed-1-8-251228`）或方舟推理接入点 ID（`ep-` 开头）。

连通性测试：

```powershell
cd C:\Users\15924\Projects\smart-assistant\apps\api
.\.venv\Scripts\python.exe -c "import asyncio; from app.services.llm import LLMService; print(asyncio.run(LLMService().ping()))"
```

或访问 `GET /health/llm/ping`。

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat/sessions` | 创建助手会话 |
| POST | `/api/v1/chat/stream` | SSE 流式对话 |
| GET | `/api/v1/users/{user_id}/service-context` | 读取用户生活服务上下文 |
| GET | `/api/v1/orders/{order_id}` | 订单详情 |
| GET | `/api/v1/vouchers/{voucher_id}` | 团购券详情 |
| POST | `/api/v1/refunds` | 创建退款申请 |
| POST | `/api/v1/chat/tickets` | 转人工工单 |
| GET | `/health/llm/ping` | 模型连通性测试 |
| GET | `/api/v1/users/{user_id}/fulfillment-events` | 履约事件列表 |
| GET | `/api/v1/users/{user_id}/operation-logs` | 操作记录列表 |
| POST | `/api/v1/workflow/actions` | 执行工作流处置动作 |

## 示例问题

- 我买的火锅套餐还能用吗？
- 券码在哪里？
- 到店核销失败，扫不出来。
- 优惠券为什么不能用？
- 我要退款。
- 这家店几点关门？
- 帮我转人工。

## P0 Demo 主故事线

```text
用户购买火锅套餐
→ 查看订单
→ 查看券码
→ 到店消费
→ 核销失败
→ AI 自动诊断
→ 重新生成核销码 / 联系商家 / 转人工
→ 问题解决
→ 消费完成
```

## 文档

- [产品说明](./docs/PRODUCT.md)
- [系统架构](./docs/ARCHITECTURE.md)

## GitHub

当前项目已 `git init`，尚未提交。确认后可执行：

```powershell
cd C:\Users\15924\Projects\smart-assistant
git add .
git commit -m "feat: rebuild as douyin life service assistant"
git branch -M main
git remote add origin https://github.com/<你的用户名>/smart-assistant.git
git push -u origin main
```

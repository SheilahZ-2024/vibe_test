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
apps/api/app/diagnosis   SDS v1 诊断引擎（Case 注册表 / 诊断树 / 动作矩阵）
deploy/init-db    PostgreSQL 领域 schema 与生活服务种子数据
docker-compose    postgres + redis + api + web(nginx)
```

### SDS v1 诊断链路

遵循《Service Diagnosis System v1》规范，每轮对话严格走：

```text
Intent识别 → 上下文获取 → 诊断树执行 → Case生成 → 工具调用 → Prompt注入 → LLM解释
```

- **Case 体系**：73 个注册 Case（IC 10 + PC 15 + FC 20 + AC 10 + CC 15 + 系统 3）
- **代码入口**：`apps/api/app/diagnosis/`（`case_specs` / `registry` / `engine` / `matrices` / `storybook`）
- **Storybook**：SB-001 ~ SB-018 口语表达库，见 `storybook.py`
- **种子数据**：`deploy/init-db/04-sds-storybook-seed.sql`、`05-sds-full-seed.sql`

### 前端体验（会话为主）

- 主界面以**会话服务**为全屏主体；订单摘要与履约进度嵌入对话区域顶部
- 输入框右侧 **+** 可打开：服务进度、历史订单、操作记录、授权设置（半屏 BottomSheet）
- 流式回复前展示**自然语言思考过程**（不暴露 Case ID、Intent 等术语给用户）
- 诊断完成后展示「您可以这样继续」动作 chips

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

无 `LLM_API_KEY` 时，系统自动使用内置 Mock 模型，仍可完整演示业务链路。

### 接入豆包（火山方舟）

在 `.env` 中配置：

```env
LLM_API_KEY=你的方舟API密钥
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL=doubao-seed-1-8-251228
LLM_TEMPERATURE=0.3
LLM_MAX_TOKENS=1200
```

注意：`LLM_MODEL` 填写豆包官网模型 ID（如 `doubao-seed-1-8-251228`）或方舟推理接入点 ID（`ep-` 开头）。

### 意图识别（轻量 LLM + 置信度阈值）

对话链路会先做一次**轻量意图分类**（非主回复 LLM），再决定是否进入工具链：

```env
INTENT_CONFIDENCE_THRESHOLD=0.65   # 达到阈值才路由到业务意图
INTENT_USE_LLM=true                # 有 API Key 时用 LLM；否则关键词兜底
INTENT_LLM_TEMPERATURE=0.1
INTENT_LLM_MAX_TOKENS=256
```

| 路由结果 | 行为 |
|----------|------|
| 置信度 ≥ 阈值 + 业务意图 | 调用对应工具链（查单/诊断/退款等） |
| 置信度 < 阈值 | `clarify`：跳过工具，模型先澄清/探明需求 |
| `chitchat` | 简短闲聊后引导回履约话题 |

SSE `pipeline` / `done` 事件会附带 `intent_meta`（原始意图、置信度、来源、备选意图）。

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
| GET | `/health` | 健康检查 |
| GET | `/health/llm/ping` | 模型连通性测试 |
| GET | `/api/v1/users/{user_id}/fulfillment-events` | 履约事件列表 |
| GET | `/api/v1/users/{user_id}/operation-logs` | 操作记录列表 |
| GET | `/api/v1/diagnosis/cases` | Case 列表 |
| GET | `/api/v1/diagnosis/cases/{case_id}` | Case 详情与推荐动作 |
| GET | `/api/v1/diagnosis/stats` | Case 统计 |
| POST | `/api/v1/workflow/actions` | 执行工作流处置动作 |

## Storybook 测试话术

| 用户说法 | 预期 Case |
|----------|-----------|
| 扫不出来 | FC-008 |
| 老板不给用 | FC-006 |
| 店关门了 | FC-001 |
| 我要退款 | AC-001 / AC-002 |
| 吃坏肚子 | CC-008（P0） |
| 那个有点问题 | CLARIFY |
| 付了钱没券 | PC-001 |

批测（诊断引擎 + 可选 API）：

```powershell
cd apps\api
.\.venv\Scripts\python.exe scripts\batch_storybook_test.py
.\.venv\Scripts\python.exe scripts\batch_storybook_test.py --api http://localhost:8000
```

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
- [阿里云部署](./docs/DEPLOY_ALIYUN.md)

## GitHub

仓库地址：https://github.com/SheilahZ-2024/vibe_test

# 抖音生活服务 · AI 履约服务管家

面向抖音生活服务 C 端用户的 **P0 Demo**：嵌入履约旅程的 **AI 履约服务管家**，帮用户把「买了券 → 预约 → 到店 → 核销 → 售后」这件事做成。

**衡量标准**：用户问题有没有被解决，而不是模型回答是否漂亮。

---

## 核心能力

| 能力 | 说明 |
|------|------|
| **会话式履约服务** | 对话为主界面，订单摘要、履约进度、服务卡片嵌入会话流 |
| **SDS v1 诊断** | 73 Case 注册表 + 完整诊断树；基于订单/券/门店客观事实与用户话术推理 |
| **ReAct 智能体** | 查单、查券、查门店、知识检索、诊断、退款、转人工等能力全部 Tool 化，轨迹可观测 |
| **流式思考 + 回复** | 全中文思考叙述；SSE 流式输出；语气润色保留事实不变 |
| **履约可视化** | 服务进度时间线（购买→预约→到店→核销→售后）；操作记录含退款金额与到账状态 |
| **120 用户 Mock 场** | 80 正常履约 + 40 异常样本；门店预约策略、券规则、POI 状态完整覆盖 |
| **实时 Mock 时间** | 规则判断用真实「现在」；启动时自动对齐业务时间到当前时刻 |

---

## 设计亮点

### 1. 数据层只放事实，诊断靠推理

Mock 数据只写入平台/商家/用户侧**可观测事实**：

- 订单状态、券有效期、`usage_rule` 文案（含「须预约 / 无需预约」）、`can_refund`
- 门店 POI（营业时间、`supports_reservation`、`business_status`、POS 同步时间）
- 履约事件、退款单记录

数据库**不预置**诊断结论或 Case 标签。跨店、缺预约、拒核销等场景，由**诊断引擎 + ReAct 智能体**读取事实后推理。

### 2. 智能体主导工具与知识

- **ReAct 循环**：模型自主决定查什么、查几次、何时 finish
- **`search_knowledge`**：按需检索平台政策/FAQ，条数由智能体决定（1~5）
- **`run_diagnosis`**：结构化诊断树参考，与规则层交叉验证后采纳
- **异常兜底**：工具或主链路异常时，结构化线索交给 LLM 生成用户可读回复，不暴露技术报错

### 3. 双层时间：规则实时 + 业务对齐

- 周末限定、午市、营业时段等按 **Asia/Shanghai 当前时刻** 计算
- Mock 业务时间以 seed 锚点为基准，API 启动时整体平移到「现在」
- 前端状态栏显示本机实时时钟

### 4. 体验对用户友好

思考区将 pipeline / 工具调用翻译为自然中文（「正在帮您查订单…」），过滤内部 Intent/Case 术语。

### 5. 120 用户一键切换

顶部 Demo 用户切换器覆盖正常履约全阶段与 40 类异常场景，适合逐项演示管家能力。

---

## 系统架构（概要）

```text
┌─────────────┐     SSE      ┌──────────────────────────────────────┐
│  apps/web   │ ◄──────────► │  apps/api (FastAPI)                  │
│  React 会话 │   /stream    │  Orchestrator → FulfillmentAgent     │
│  BottomSheet│              │    (ReAct) → Tools → DiagnosisEngine │
└─────────────┘              └──────────┬─────────────┬─────────────┘
                                        │             │
                                   PostgreSQL       Redis
                                   (领域+知识库)    (会话)
```

**一次对话路径**：用户输入 → EdgeContext → 意图识别 → 拉取 service-context → ReAct 选工具（含 search_knowledge / run_diagnosis）→ LLM 撰写并润色回复。

详细说明见 **[docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)**。

---

## 快速开始

### 依赖

- Docker Desktop（Running）
- Git、Node 22、Python 3.12（本地开发可选）

### 启动（推荐 Docker）

```powershell
cd C:\Users\15924\Projects\smart-assistant
copy .env.example .env   # 首次
docker compose up --build -d
```

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:5173 |
| API 文档 | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/health |

API 每次启动会自动：schema migrate → 知识库 bootstrap → bulk seed（版本落后时重灌）→ mock 时间对齐。

### 接入豆包（火山方舟）

```env
LLM_API_KEY=你的方舟API密钥
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL=doubao-seed-1-8-251228
LLM_REQUIRE_LIVE=true
```

### 本地体验建议

1. 打开 http://localhost:5173 ，切换 Demo 用户
2. 正常用户：「查看券码」「服务进度到哪了」
3. 异常用户（081+）：「扫不出来」「老板说不认券」「没预约能核销吗」
4. 点击 **+** 查看服务进度、历史订单、操作记录

---

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat/sessions` | 创建会话 |
| POST | `/api/v1/chat/stream` | SSE 流式对话 |
| GET | `/api/v1/users/{id}/service-context` | 用户履约上下文 |
| GET | `/api/v1/users/{id}/orders/{oid}/fulfillment-timeline` | 履约时间线 |
| GET | `/api/v1/users/{id}/service-records` | 操作记录 |
| POST | `/api/v1/refunds` | 创建退款 |
| POST | `/api/v1/workflow/actions` | 执行处置动作 |
| GET | `/api/v1/diagnosis/cases` | Case 列表 |

完整列表：http://localhost:8000/docs

---

## Mock 数据维护

```powershell
py -3.12 scripts/generate_mock_data.py    # 重新生成 SQL
docker compose restart api                 # 触发 v6+ 自动重灌
```

Seed 文件：`deploy/init-db/03-bulk-seed.sql`（当前 `bulk_seed_version=6`）。

---

## 文档

| 文档 | 内容 |
|------|------|
| [docs/DEMO_GUIDE.md](./docs/DEMO_GUIDE.md) | Demo 样本对照与演示脚本 |
| [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) | 系统架构详解 |
| [docs/PRODUCT.md](./docs/PRODUCT.md) | 产品原则与 Agent 定义 |
| [docs/DEPLOY_ALIYUN.md](./docs/DEPLOY_ALIYUN.md) | 阿里云手动部署 |

---

## 仓库

https://github.com/SheilahZ-2024/vibe_test

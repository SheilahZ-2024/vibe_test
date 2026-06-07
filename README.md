# 抖音生活服务 · AI 履约服务管家

面向抖音生活服务 C 端用户的 **P0 Demo**：嵌入履约旅程的 **AI 履约服务管家**，帮用户把「买了券 → 预约 → 到店 → 核销 → 售后」这件事做完、做好。

**成功标准**：用户问题有没有被解决，而不是模型回答是否漂亮。

---

## 这是什么

| 维度 | 说明 |
|------|------|
| **产品形态** | 手机壳内的会话式服务界面，不是独立 FAQ 机器人 |
| **核心任务** | 查单、解释规则、诊断失败原因、引导办理（预约/退款/转人工等） |
| **技术特点** | 统一 **Plan → Gather → fact_sheet → Compose（含 Verify）→ Emit** 管线；Gather 由模型选工具/规则 |
| **数据原则** | 数据库只存客观业务事实；诊断 Case 在运行时由引擎 + 智能体推理得出 |
| **演示规模** | 120 个 Mock 用户（80 正常履约 + 40 异常样本），一键切换 |

---

## 核心能力一览

| 能力 | 用户侧表现 | 技术实现 |
|------|-----------|----------|
| **会话式履约** | 对话为主界面，订单摘要、进度卡片、操作按钮嵌入会话流 | `App.tsx` + SSE 流式 |
| **Gather ReAct 核实** | 思考区灰字展示「正在核对什么规则、查到了什么」 | `BoundedGatherReAct`（1~3 步/轮） |
| **单次 Compose 成稿** | 正式气泡给出结论 + emoji + 可执行建议 | `DecisionComposer` + 可选 `ReplyPolisher` |
| **SDS v1 诊断** | 跨店、缺预约、闭店、拒核销等场景可解释 | 73 Case 注册表 + 诊断树 |
| **流式思考 + 回复** | 先看到推理过程，再看到正式回复 | `thinking_token` + `token` SSE |
| **履约可视化** | + 半屏：服务进度时间线、历史订单、操作记录 | `ServicePanels` / `FulfillmentContextCard` |
| **写操作确认** | 退款、预约、转人工等需用户点确认 | `ActionSheet` → `/workflow/actions` |
| **120 用户 Mock 场** | 顶部切换 Demo 用户，覆盖全阶段与 40 类异常 | `generate_mock_data.py` + bulk seed v6 |
| **实时 Mock 时间** | 周末/午市/营业时段按真实「现在」判断 | `mock_time_shift.py` 启动对齐 |

---

## 系统架构（概要）

```text
┌─────────────────────────────────────────────────────────────────┐
│  apps/web（前端）                                                │
│  会话主界面 · 思考流 · 焦点订单 · Demo 用户 · + 半屏服务面板      │
└────────────────────────────┬────────────────────────────────────┘
                             │ POST /api/v1/chat/stream（SSE 流式）
┌────────────────────────────▼────────────────────────────────────┐
│  apps/api（后端 FastAPI）                                        │
│                                                                  │
│  ChatOrchestrator（编排层）                                      │
│    └─ FulfillmentAgent（薄封装）                                 │
│         └─ UnifiedTurnPipeline（统一 Turn 管线）                 │
│              ├─ TurnPlanner        意图路由 + 接话模式           │
│              ├─ BoundedGatherReAct 有界 Gather（模型选工具）     │
│              ├─ fact_sheet           程序汇总事实（独立模块，非 SDS）│
│              ├─ DecisionComposer     单次成稿 LLM（内含 Verify 校验）│
│              └─ ReplyPolisher        可选语气润色 + emoji            │
│                                                                  │
│  AgentToolExecutor → LifeServiceTools → DiagnosisEngine（SDS）   │
└──────────────┬──────────────────────────────┬───────────────────┘
               │                              │
          PostgreSQL                        Redis
        （订单/券/门店/知识库）            （会话 + 跨轮记忆）
```

**一次用户消息的完整路径**：

```text
用户输入
  → TurnPlanner（Plan · 规划）
      关键词/轻量 LLM 识别意图；判定接话模式（新话题/续问/致谢）
  → BoundedGatherReAct（Gather · 核实）
      模型决定查哪些规则、调用哪些只读工具或 run_diagnosis；最多 3 步
  → build_fact_sheet（事实表 · 独立程序模块）
      汇总工具查库结果 + usage_rules 推导 + SDS Case 标签；不汇总 LLM thought
  → DecisionComposer（Compose · 成稿，内含 Verify）
      唯一成稿 LLM；Verify 在模块内部检查 JSON，失败则同一 LLM 重写
  → Emit（输出）
      thinking_token 推送推理；token 流式推送正式回复
```

典型每轮 **2~4 次 LLM**（致谢接话 0 次）。详见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)。

---

## 设计原则（为什么这样建）

### 1. 数据层只放事实，诊断靠推理

Mock 数据写入的是平台/商家/用户侧**可观测事实**：

- 订单状态、券有效期、`usage_rule` 文案、是否可退
- 门店 POI（营业时间、`supports_reservation`、`business_status`）
- 履约事件、退款单记录

**不预置**诊断结论或 Case 标签。跨店、缺预约、拒核销等，由 Gather 调工具 + `run_diagnosis` 后在 Compose 阶段解释给用户。

### 2. 模型主导核实，程序负责硬约束

| 阶段 | 谁做主 | 做什么 |
|------|--------|--------|
| **Gather ReAct** | 大模型 | 决定核对哪些规则、调用什么工具 |
| **fact_sheet** | 程序 | 汇总查库 + 规则 + Case 标签；供 Compose/Verify/跨轮记忆 |
| **Compose** | 大模型 | 单次成稿（模块内部含 Verify 程序校验） |
| **写操作** | 用户确认 | Gather 阶段禁止写；需 `ActionSheet` 确认 |

### 3. 思考区透传真实推理

Gather 的 `thought`、工具 observation、Compose 的 `understanding` / `reasoning` 经 `thinking_narrative` 清洗后以 **thinking_token** 流式展示。内部 Intent 代码、Case 编号（如 PC-010）**不暴露**给用户。

### 4. 双层时间

- **规则判断**：周末限定、午市、营业时段 → 按 **Asia/Shanghai 当前时刻**
- **业务数据**：seed 相对锚点写入，API 启动时整体平移到「现在」

---

## 快速开始

### 依赖

- Docker Desktop（Running）
- Git、Node 20+、Python 3.12（本地开发可选）

### 启动（推荐 Docker）

```powershell
cd C:\Users\15924\Projects\smart-assistant
copy .env.example .env   # 首次：填入 LLM_API_KEY
docker compose up --build -d
```

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:5173 |
| API 文档 | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/health |

API 每次启动自动执行：schema migrate → 知识库 bootstrap → bulk seed（版本落后时重灌 v6）→ mock 时间对齐。

### 接入豆包（火山方舟）

```env
LLM_API_KEY=你的方舟API密钥
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL=doubao-seed-1-8-251228
LLM_REQUIRE_LIVE=true
LLM_FALLBACK_TO_MOCK=false
```

### 关键环境变量

| 变量 | 默认（.env.example） | 说明 |
|------|---------------------|------|
| `AGENT_GATHER_MAX_STEPS` | 3 | Gather ReAct 每轮最多几步 |
| `AGENT_COMPOSE_MAX_TOKENS` | 768 | Compose 成稿 token 上限 |
| `AGENT_TONE_POLISH_ENABLED` | **false** | true = 二次 LLM 润色 + emoji（略慢） |
| `AGENT_PREFETCH_FOCUS_BUNDLE` | true | 有焦点订单时程序预拉 bundle |
| `INTENT_CONFIDENCE_THRESHOLD` | 0.65 | 高于此值不调 LLM 做意图分类 |
| `AGENT_HISTORY_MAX_TURNS` | 4 | 带入上下文的最近轮数 |

> 注意：`config.py` 中 `AGENT_TONE_POLISH_ENABLED` 代码默认 `true`，以 `.env` 为准。生产/Demo 建议保持 `false`，emoji 由 Compose prompt 要求。

### 本地体验建议

1. 打开 http://localhost:5173 ，顶部切换 Demo 用户
2. **正常用户**（001~080）：「查看券码」「服务进度到哪了」
3. **异常用户**（081+）：「扫不出来」「老板说不认券」「没预约能核销吗」
4. 点击 **+** 查看服务进度、历史订单、操作记录

推荐 5 分钟脚本见 [docs/DEMO_GUIDE.md](./docs/DEMO_GUIDE.md)。

---

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat/sessions` | 创建会话 |
| POST | `/api/v1/chat/stream` | SSE 流式对话（主入口） |
| GET | `/api/v1/users/sample` | Demo 用户随机抽样 |
| GET | `/api/v1/users/{id}/service-context` | 用户履约上下文 |
| GET | `/api/v1/users/{id}/orders/{oid}/fulfillment-timeline` | 履约时间线 |
| GET | `/api/v1/users/{id}/service-records` | 操作记录 |
| POST | `/api/v1/refunds` | 创建退款 |
| POST | `/api/v1/workflow/actions` | 执行写操作（预约/退款/转人工等） |
| GET | `/api/v1/diagnosis/cases` | Case 列表 |

完整列表：http://localhost:8000/docs

---

## Mock 数据维护

```powershell
py -3.12 scripts/generate_mock_data.py    # 重新生成 SQL
docker compose restart api                 # 触发 v6+ 自动重灌
```

- 输出：`deploy/init-db/03-bulk-seed.sql`
- 当前版本：**bulk_seed_version = 6**（门店预约策略 walk_in / must_reserve 拆分）
- 120 用户：`user_001` ~ `user_120`，每人 1 订单 + 1 团购券

---

## 文档索引

| 文档 | 内容 |
|------|------|
| [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) | **系统架构详解**（管线各阶段、工具、SSE、数据模型） |
| [docs/PRODUCT.md](./docs/PRODUCT.md) | **产品定义**（定位、场景矩阵、Agent 闭环、UI 原则） |
| [docs/DEMO_GUIDE.md](./docs/DEMO_GUIDE.md) | Demo 样本对照与 5 分钟演示脚本 |
| [docs/DEPLOY_ALIYUN.md](./docs/DEPLOY_ALIYUN.md) | 阿里云 ECS 手动部署 |

---

## 仓库

https://github.com/SheilahZ-2024/vibe_test

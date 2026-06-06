# 抖音生活服务 · AI 履约服务管家

面向抖音生活服务 C 端用户的 **P0 Demo**。它不是 FAQ、智能客服或独立聊天机器人，而是嵌入履约旅程的 **AI 履约服务管家**——帮用户把「买了券 → 预约 → 到店 → 核销 → 售后」这件事做成。

**衡量标准**：用户问题有没有被解决，而不是模型回答是否漂亮。

---

## 核心能力

| 能力 | 说明 |
|------|------|
| **会话式履约服务** | 以对话为主界面，订单摘要、履约进度、服务卡片嵌入会话流 |
| **SDS v1 诊断** | 73 Case 注册表 + 诊断树；根据订单/券/门店**客观事实**与用户话术推理 |
| **ReAct 工具链** | 查单、查券、查门店、诊断、退款、转人工等能力全部走 Tool，结果可观测 |
| **流式思考 + 回复** | 全中文思考叙述（不暴露 Case ID / Intent 术语）；SSE 流式输出 |
| **履约可视化** | 服务进度时间线（购买→预约→到店→核销→售后）；操作记录含退款金额与到账状态 |
| **120 用户 Mock 场** | 80 正常履约 + 9 售后 + 40 异常样本；**不预填**对话与操作记录，等用户来问 |
| **实时 Mock 时间** | 规则判断用真实「现在」；API 启动时 `mock_time_shift` 将业务时间对齐当前时刻 |

---

## 设计亮点

### 1. 数据层只放事实，诊断靠推理

Mock 生成器（`scripts/generate_mock_data.py`）只写入平台/商家/用户侧可观测数据：

- 订单状态、券有效期、`usage_rule` 文案、`can_refund`
- 门店 POI（营业时间、`business_status`、搬迁旧址、POS 同步时间）
- 履约事件、退款单记录

**禁止**写入 `merchant_reject`、`store_mismatch`、`diagnosis_case` 等诊断捷径。跨店场景通过「订单门店 ≠ 券适用门店」等**关系事实**表达；拒核销等现场问题靠**用户描述 + 引擎规则**推导。

### 2. 双层时间：规则实时 + 启动对齐

- **引擎规则**（周末限定、午市、营业时段）按 `Asia/Shanghai` **当前时刻**计算
- **Mock 业务时间**以 `SEED_ANCHOR` 为基准生成，每次 API 启动 `mock_time_shift` 整体平移到「现在」（±15 分钟抖动）
- 前端状态栏时钟（`PhoneShell`）同步显示本机实时时间

### 3. 思考区对用户友好

`thinking_narrative.py` 将 pipeline / 工具调用翻译为「您可能是想咨询…」「正在帮您查订单…」等自然中文，过滤英文 intent 名与内部术语。

### 4. 意图置信度门控

轻量 LLM（或关键词兜底）先做意图分类；低于阈值走 `clarify` 澄清，避免误触发工具链。主回复 LLM 可配置 `LLM_REQUIRE_LIVE` 禁止静默 Mock。

### 5. 可切换 Demo 用户

顶部用户切换器在 120 个 mock 用户间切换；**user_081 ~ user_120** 为异常样本（跨店、过期、POS 不同步、门店闭店等），适合逐项体验诊断能力。

---

## 系统架构（概要）

```text
┌─────────────┐     SSE      ┌──────────────────────────────────────┐
│  apps/web   │ ◄──────────► │  apps/api (FastAPI)                  │
│  React 会话 │   /stream    │  Orchestrator → Agent(ReAct) → Tools │
│  BottomSheet│              │           ↘ DiagnosisEngine (SDS v1) │
└─────────────┘              └──────────┬─────────────┬─────────────┘
                                        │             │
                                   PostgreSQL       Redis
                                   (领域+知识库)    (会话)
```

**一次对话路径**：用户输入 → EdgeContext（授权/焦点订单）→ 意图识别 → 拉取 service-context → 知识库检索 → ReAct 选工具 → 诊断树（若核销/售后类）→ Prompt 注入 Case + 动作 → LLM 流式解释。

详细分层、模块表、数据流与 seed 机制见 **[docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)**。

---

## 快速开始

### 依赖

- Docker Desktop（Running）
- Git、Node 22、Python 3.12（本地开发可选）

终端找不到命令时：

```powershell
cd C:\Users\15924\Projects\smart-assistant
. .\scripts\refresh-path.ps1
```

### 启动（推荐 Docker）

```powershell
cd C:\Users\15924\Projects\smart-assistant
copy .env.example .env   # 首次
docker compose up --build -d
```

从旧版数据库升级（会清空 Demo 数据并重灌 v5 seed）：

```powershell
docker compose down -v
docker compose up --build -d
```

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:5173 |
| API 文档 | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/health |

API 每次启动会自动：`migrate` → 知识库/bootstrap → bulk seed（版本落后时重灌）→ **mock 时间对齐**。

### 接入豆包（火山方舟）

```env
LLM_API_KEY=你的方舟API密钥
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL=doubao-seed-1-8-251228
LLM_REQUIRE_LIVE=true          # 对话主链路禁止静默 Mock
LLM_FALLBACK_TO_MOCK=true      # 仅非主链路可降级
```

### 本地体验建议

1. 打开 http://localhost:5173 ，切换不同 Demo 用户
2. 正常用户：「查看券码」「我的订单到哪一步了」
3. 异常用户（081+）：「扫不出来」「老板说不认券」「我要退款」「店关门了」
4. 点击 **+** 查看服务进度、历史订单、操作记录

---

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat/sessions` | 创建会话 |
| POST | `/api/v1/chat/stream` | SSE 流式对话 |
| GET | `/api/v1/users/{id}/service-context` | 用户履约上下文 |
| GET | `/api/v1/users/{id}/orders/{oid}/fulfillment-timeline` | 履约时间线 |
| GET | `/api/v1/users/{id}/service-records` | 操作记录（含退款） |
| POST | `/api/v1/refunds` | 创建退款 |
| POST | `/api/v1/workflow/actions` | 执行处置动作 |
| GET | `/api/v1/diagnosis/cases` | Case 列表 |

完整列表见 Swagger：http://localhost:8000/docs

---

## Mock 数据维护

```powershell
# 重新生成 SQL（改剧本/字段后）
py -3.12 scripts/generate_mock_data.py

# 手动对齐时间（通常 API 启动已自动执行）
py -3.12 scripts/shift_mock_timestamps.py
```

Seed 文件：`deploy/init-db/03-bulk-seed.sql`（`bulk_seed_version=5`）。

---

## Storybook 批测（开发）

| 用户说法 | 典型 Case |
|----------|-----------|
| 扫不出来 | FC-008 |
| 老板不给用 | FC-006 |
| 店关门了 | FC-001 |
| 我要退款 | AC-001 / AC-002 |
| 吃坏肚子 | CC-008（P0） |

```powershell
cd apps\api
.\.venv\Scripts\python.exe scripts\batch_storybook_test.py --api http://localhost:8000
```

---

## 文档

| 文档 | 内容 |
|------|------|
| [docs/DEMO_GUIDE.md](./docs/DEMO_GUIDE.md) | **Demo 样本编号对照与演示脚本** |
| [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) | 系统架构详解（分层、对话流、SDS、seed、时间） |
| [docs/PRODUCT.md](./docs/PRODUCT.md) | 产品原则与 Agent 定义 |
| [docs/DEPLOY_ALIYUN.md](./docs/DEPLOY_ALIYUN.md) | 阿里云部署 |

---

## 仓库

https://github.com/SheilahZ-2024/vibe_test

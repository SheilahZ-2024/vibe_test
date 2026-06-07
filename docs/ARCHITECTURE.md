# 系统架构详解

AI 履约服务管家的技术分层、关键设计与数据流。

> 主链路：**TurnPlanner → BoundedGatherReAct → DecisionComposer → DecisionVerifier → Emit**  
> 旧版多轮 ReAct + 独立润色已移除；`fulfillment_agent.py` 仅作 Pipeline 薄封装。

---

## 1. 设计目标

| 目标 | 实现 |
|------|------|
| 帮用户**完成履约** | 会话 + 工具办理 + 可执行建议 |
| 诊断可解释 | SDS 诊断树读 DB 事实 + 规则推导 Case |
| Demo 长期可玩 | 相对时间 seed + 启动 mock 时间对齐 |
| 体验专业友好 | 思考区中文化；内部 Case/Intent 不暴露给用户 |

---

## 2. 总体架构

```mermaid
flowchart TB
  subgraph client ["apps/web"]
    UI["App.tsx 会话主界面"]
    Sheet["BottomSheet: 进度/订单/记录"]
    Edge["EdgeContext 授权包"]
  end

  subgraph api ["apps/api"]
    Chat["routers/chat.py SSE"]
    Orch["ChatOrchestrator"]
    Agent["FulfillmentAgent\nUnifiedTurnPipeline"]
    Plan["TurnPlanner"]
    Gather["BoundedGatherReAct"]
    Compose["DecisionComposer"]
    Verify["DecisionVerifier"]
    Tools["AgentToolExecutor"]
    DX["DiagnosisEngine SDS v1"]
    Recovery["ErrorRecoveryService"]
    LLM["LLMService"]
  end

  subgraph data ["数据层"]
    PG[("PostgreSQL")]
    RD[("Redis")]
  end

  UI --> Chat
  Edge --> Chat
  Chat --> Orch
  Orch --> Agent
  Agent --> Plan
  Agent --> Gather
  Gather --> Tools
  Agent --> Compose
  Compose --> Verify
  Compose --> LLM
  Tools --> DX
  Orch --> Recovery
  Tools --> PG
  Chat --> RD
  Sheet --> PG
```

### 2.1 仓库结构

```text
apps/web/                 React + Vite + Tailwind
apps/api/app/
  routers/chat.py         SSE 对话入口
  services/
    orchestrator.py       会话 I/O、pipeline 事件
    fulfillment_agent.py  统一 Pipeline 对外入口
    unified_turn_pipeline.py  Plan → Gather → Compose → Emit
    turn_plan.py          轻量路由（意图/接话，不硬编码工具）
    gather_react.py       有界 Gather ReAct（模型选工具/规则）
    gather_prompts.py     Gather ReAct 提示词
    evidence_gatherer.py    Mock 程序回退 Gather
    decision_composer.py  单次 Compose LLM
    decision_verifier.py  程序校验 + 重试
    compose_prompts.py    Compose 提示词
    agent_tools.py        工具执行器
    error_recovery.py     异常兜底（LLM + 结构化线索）
    tools.py              领域查询/写操作
    usage_rules.py        券规则/营业时段解析
    conversation_memory.py 跨轮 fact_sheet / digest
    thinking_narrative.py 思考清洗（透传模型 thought）
    thinking_stream.py     thinking_token 流式推送
  diagnosis/              SDS v1：registry, engine, matrices
  db/
    bulk_bootstrap.py     mock 幂等重灌（version 检测）
    mock_time_shift.py    业务时间对齐
deploy/init-db/           Postgres 初始化 SQL
scripts/generate_mock_data.py
```

---

## 3. 一次对话的完整路径

```mermaid
sequenceDiagram
  participant U as 用户
  participant W as Web
  participant O as Orchestrator
  participant A as FulfillmentAgent
  participant T as Tools
  participant D as DiagnosisEngine
  participant L as LLM

  U->>W: 输入
  W->>O: POST /chat/stream
  O->>A: run_stream
  A->>L: 意图分类（TurnPlanner，仅路由）
  loop Gather ReAct 1~3 步
    A->>L: 查什么规则/用什么工具？
    A->>T: 只读 tool 或 run_diagnosis
    T->>D: diagnose 可选
    D-->>T: CaseDiagnosisResult
    T-->>A: observation → 回传 ReAct
  end
  A->>L: Compose 单次 JSON（理解+推理+自监督+成稿）
  A->>A: DecisionVerifier 程序校验
  L-->>W: SSE token（Compose 成稿；可选 tone polish）
  L-->>W: SSE thinking_token（Gather/Compose 推理流）
  O-->>W: SSE done
```

### 3.1 EdgeContext

前端打包：隐私授权、`user_id`、焦点订单 `focus_order_id`、行为摘要。Orchestrator 据此拉取 service-context 并默认查单对象。

### 3.2 意图门控

关键词优先 + 轻量 LLM；置信度低于阈值走 `clarify`；`chitchat` 短回复并引导回履约话题。

### 3.3 统一 Turn Pipeline（Gather ReAct + Compose）

每轮用户消息固定走 **Plan → Gather ReAct → Compose → Verify → Emit**：

1. **TurnPlanner（轻量）**：意图分类 + `task_type` + 接话模式；**不**硬编码工具清单
2. **BoundedGatherReAct（有界 1~3 步）**：模型主导
   - 决定核对哪些**规则**（`rules_to_check`）
   - 选择**只读工具** / `run_diagnosis` / `search_knowledge`
   - 每步 `thought → action → observation` 写入 trace
   - 结束时 `gather_complete` + `gather_summary`；写操作不在此阶段执行
3. **fact_sheet**：程序从 tool_calls + 诊断结果结构化抽取
4. **DecisionComposer**：**唯一成稿 LLM**；消费 **完整 Gather trace** + fact_sheet + 诊断
5. **DecisionVerifier**：预约硬性约束等程序校验
6. **Emit**：流式输出 reply；`AGENT_TONE_POLISH_ENABLED=true` 时可选二次润色（补 emoji）

致谢接话：`skip_gather_react` + Compose 模板，0~1 次 LLM。

配置：`AGENT_GATHER_MAX_STEPS=3`、`AGENT_GATHER_*`、`AGENT_COMPOSE_*`、`AGENT_TONE_POLISH_ENABLED`（默认 false）。

### 3.4 异常处理

| 层级 | 行为 |
|------|------|
| 工具异常 | 返回结构化 `clues`，Gather 写入 trace |
| 主链路崩溃 | `ErrorRecoveryService` 将上下文交给 LLM 生成可读回复 |

不向用户暴露 Python 堆栈或内部术语。

### 3.5 思考区

| 来源 | 展示内容 |
|------|----------|
| Gather 预取 / 工具 | observation 事实摘要（订单/券/门店） |
| Gather ReAct | 模型 `thought`、`rules_to_check`、诊断 Case |
| Compose | `understanding.user_goal`、`reasoning.rule_application` |

`thinking_stream.py` 以 **thinking_token** 带节奏流式推送；前端 `ThinkingStream` 按段灰字展示。`thinking_narrative._sanitize` 替换工具名、剥离 Case 编号。

### 3.6 跨轮记忆

`conversation_memory` 持久化 `fact_sheet`、`gather_summary`、`digest`，供接话轮 Gather ReAct 复用。

---

## 4. SDS v1 诊断系统

```text
Intent → DiagnosisContext → 诊断树逐步校验 → Case → 动作矩阵 → 供 Agent 参考
```

- **73** 注册 Case（IC / PC / FC / AC / CC）
- 输入：订单、券、门店、用户原话
- 输出：步骤、Case ID、推荐动作（不直接写用户回复）

### 推理示例

| Case | 依据事实 |
|------|----------|
| PC-008 跨店 | `order.store_id ≠ voucher.store_id` |
| PC-009 时段 | `usage_rule` + 当前星期/时刻 |
| PC-010 缺预约 | 规则须预约 + 订单无 `reservation_confirmed` |
| FC-001 闭店 | `business_status = suspended` |
| FC-006 拒核销 | 券有效 + 用户描述「老板不给用」 |

---

## 5. 前端架构

- **主屏**：会话 + 焦点订单 + 思考流 + 快捷话术
- **+ 半屏**：履约时间线、历史订单、操作记录、授权
- **DemoUserSwitcher**：120 用户
- **SSE**：`thinking_token` / `token` / `gather_step` / `pipeline` / `done`

---

## 6. 数据模型

| 表 | 说明 |
|----|------|
| `users` | C 端用户 |
| `merchant_stores` | 门店 POI、`supports_reservation`、metadata |
| `life_orders` | 订单 + metadata（预约记录等） |
| `vouchers` | 团购券 + **usage_rule 文案** |
| `coupons` | 平台优惠券 |
| `refund_cases` | 退款/售后 |
| `fulfillment_events` | 履约事件时间线 |
| `knowledge_articles` | 平台知识库 |
| `conversation_events` | 对话与工具日志 |

库中**无**诊断 Case 标签；仅客观业务事实。

---

## 7. Mock 数据机制

### 生成

`scripts/generate_mock_data.py` → `deploy/init-db/03-bulk-seed.sql`

- 120 用户：80 正常 + 40 异常
- 门店预约策略：约一半 `must_reserve`、一半 `walk_in`
- 时间相对 `SEED_ANCHOR` 写入

### 启动 bootstrap

1. Schema migrate  
2. 知识库 seed  
3. **`ensure_bulk_seed`**：版本 `< 6` 时 truncate mock 用户数据并重灌  
4. **`shift_mock_timestamps`**：对齐到当前时刻  

当前版本：**bulk_seed_version = 6**

---

## 8. 部署拓扑

| 服务 | 端口 | 说明 |
|------|------|------|
| `web` | 5173→80 | Nginx + API 反代 |
| `api` | 8000 | FastAPI |
| `postgres` | 5432 | 领域数据 |
| `redis` | 6379 | 会话 |

详见 [DEPLOY_ALIYUN.md](./DEPLOY_ALIYUN.md)。

---

## 9. 扩展方向

- 真实生活服务 Open API 对接  
- 向量检索知识库  
- 工单坐席端、OpenTelemetry  
- 门店适用列表独立表  

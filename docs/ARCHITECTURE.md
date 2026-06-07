# 系统架构详解

AI 履约服务管家的技术分层、关键模块与数据流。本文档与源码对齐，术语采用 **「中文名（EnglishName）」** 格式，便于阅读与检索。

> **主链路**：`TurnPlanner` → `BoundedGatherReAct` → `DecisionComposer` → `DecisionVerifier` → `Emit`  
> **入口文件**：`apps/api/app/services/unified_turn_pipeline.py`  
> 旧版多轮 ReAct Agent 已移除；`fulfillment_agent.py` 仅为 Pipeline 薄封装。

---

## 1. 设计目标

| 目标 | 实现方式 |
|------|----------|
| 帮用户**完成履约** | 会话 + 只读工具核实 + 写操作办理 + 可执行建议 |
| 诊断**可解释** | SDS 诊断树读 DB 事实 + 规则推导 Case，思考区展示推理过程 |
| Demo **长期可玩** | 相对时间 seed + 启动时 mock 时间对齐到当前 |
| 体验**专业友好** | 思考区中文化；内部 Case/Intent 编号不暴露给用户 |
| **成本可控** | 每轮 2~4 次 LLM；Gather 有界 3 步；Compose 单次成稿 |

---

## 2. 总体架构

### 2.1 分层图

```mermaid
flowchart TB
  subgraph client ["客户端 apps/web"]
    UI["App.tsx 会话主界面"]
    Sheet["BottomSheet 半屏面板"]
    Edge["EdgeContext 授权上下文包"]
  end

  subgraph api ["服务端 apps/api"]
    Chat["routers/chat.py SSE 入口"]
    Orch["ChatOrchestrator 编排层"]
    Agent["FulfillmentAgent 智能体入口"]
    Pipe["UnifiedTurnPipeline 统一管线"]
    Plan["TurnPlanner 轮次规划"]
    Gather["BoundedGatherReAct 有界 Gather"]
    Compose["DecisionComposer 决策成稿"]
    Verify["DecisionVerifier 程序校验"]
    Tools["AgentToolExecutor 工具执行器"]
    DX["DiagnosisEngine SDS 诊断引擎"]
    Recovery["ErrorRecoveryService 异常兜底"]
    LLM["LLMService 大模型服务"]
  end

  subgraph data ["数据层"]
    PG[("PostgreSQL 业务库")]
    RD[("Redis 会话缓存")]
  end

  UI --> Chat
  Edge --> Chat
  Chat --> Orch
  Orch --> Agent
  Agent --> Pipe
  Pipe --> Plan
  Pipe --> Gather
  Gather --> Tools
  Pipe --> Compose
  Compose --> Verify
  Compose --> LLM
  Tools --> DX
  Orch --> Recovery
  Tools --> PG
  Chat --> RD
  Sheet --> PG
```

**各层中文说明**：

| 英文模块 | 中文职责 |
|----------|----------|
| **ChatOrchestrator** | 会话 I/O：校验用户、拉 service-context、转发 SSE、持久化对话、写 Redis 跨轮记忆 |
| **FulfillmentAgent** | 对外 Agent 入口，100% 委托 `UnifiedTurnPipeline` |
| **UnifiedTurnPipeline** | 单轮业务决策核心：Plan → Gather → Compose → Verify → Emit |
| **TurnPlanner** | 轻量路由：意图 + 接话模式；**不**硬编码 Gather 工具清单 |
| **BoundedGatherReAct** | 有界 ReAct 循环：模型选规则/工具，最多 N 步 |
| **DecisionComposer** | 唯一成稿 LLM：消费 Gather trace + fact_sheet 输出 JSON |
| **DecisionVerifier** | 程序校验：预约硬约束、fact 一致性等（非独立 LLM 阶段） |
| **AgentToolExecutor** | 执行 Agent 工具，桥接诊断引擎与领域查询 |
| **DiagnosisEngine** | SDS v1：规则树 → Case → 推荐动作（advisory，不直接当用户回复） |

### 2.2 仓库结构

```text
smart-assistant/
├── apps/
│   ├── web/                          # 前端 React + Vite + Tailwind
│   │   └── src/
│   │       ├── App.tsx               # 主界面编排
│   │       ├── api/client.ts         # SSE 客户端 + EdgeContext 构建
│   │       ├── components/
│   │       │   ├── ThinkingStream.tsx    # 思考区灰字流
│   │       │   ├── DemoUserSwitcher.tsx  # Demo 用户切换
│   │       │   ├── OrderFocusPanel.tsx   # 多订单焦点切换
│   │       │   └── ServicePanels.tsx     # 时间线/操作记录
│   │       └── lib/thinkingReveal.ts     # 思考跟显逻辑
│   │
│   └── api/app/
│       ├── routers/chat.py           # POST /chat/stream → SSE
│       ├── config.py                 # 环境变量与默认值
│       ├── services/
│       │   ├── orchestrator.py       # ChatOrchestrator
│       │   ├── fulfillment_agent.py  # Agent 薄封装
│       │   ├── unified_turn_pipeline.py  # ★ 统一管线主文件
│       │   ├── turn_plan.py          # TurnPlanner + TurnPlan
│       │   ├── intent.py             # IntentClassifier 意图识别
│       │   ├── gather_react.py       # BoundedGatherReAct
│       │   ├── gather_prompts.py       # Gather 提示词
│       │   ├── evidence_gatherer.py  # Mock 模式程序 Gather 回退
│       │   ├── decision_composer.py  # DecisionComposer
│       │   ├── decision_verifier.py  # DecisionVerifier
│       │   ├── compose_prompts.py    # Compose 提示词
│       │   ├── fact_sheet.py         # 事实表抽取
│       │   ├── agent_tools.py        # AgentToolExecutor
│       │   ├── tool_catalog.py       # 工具目录与意图裁剪
│       │   ├── tools.py              # LifeServiceTools 领域查询
│       │   ├── conversation_memory.py # Redis 跨轮记忆
│       │   ├── thinking_stream.py    # thinking_token 流式推送
│       │   ├── thinking_narrative.py # 思考文案清洗/中文化
│       │   ├── reply_polisher.py     # 可选语气润色
│       │   ├── error_recovery.py     # 异常兜底
│       │   └── context.py            # ServiceContextBuilder
│       ├── diagnosis/                # SDS v1 诊断系统
│       │   ├── engine.py             # DiagnosisEngine
│       │   ├── registry.py           # Case 注册
│       │   └── case_specs.py         # 73 Case 规格定义
│       └── db/
│           ├── bulk_bootstrap.py     # Mock 幂等重灌
│           └── mock_time_shift.py    # 业务时间对齐
├── deploy/init-db/                   # Postgres 初始化 SQL
├── scripts/generate_mock_data.py     # Mock 数据生成
└── docs/                             # 项目文档
```

---

## 3. 统一 Turn Pipeline（核心）

每一轮用户消息走固定五段：**Plan → Gather → Compose → Verify → Emit**。

### 3.1 时序图

```mermaid
sequenceDiagram
  participant U as 用户
  participant W as Web 前端
  participant O as Orchestrator 编排层
  participant P as UnifiedTurnPipeline 管线
  participant G as Gather ReAct
  participant T as Tools 工具层
  participant D as DiagnosisEngine 诊断
  participant C as Compose 成稿
  participant L as LLM 大模型

  U->>W: 输入消息
  W->>O: POST /chat/stream
  O->>P: run_stream
  P->>L: TurnPlanner 意图（可选 0~1 次）
  loop Gather ReAct 1~3 步
    P->>G: 下一步查什么？
    G->>L: thought + action JSON
    G->>T: 只读 tool / run_diagnosis
    T->>D: diagnose（若调用诊断）
    D-->>T: CaseDiagnosisResult
    T-->>G: observation 观察结果
    G-->>W: thinking_token 思考流
  end
  P->>P: build_fact_sheet 事实表
  P->>C: Compose 成稿
  C->>L: 单次 JSON（理解+推理+回复）
  C->>C: DecisionVerifier 校验
  alt 校验失败
    C->>L: 重试 Compose（最多 1 次）
  end
  C-->>W: thinking_token Compose 推理
  P-->>W: token 正式回复流
  O-->>W: done 结束事件
```

### 3.2 Plan — 轮次规划（TurnPlanner）

**文件**：`turn_plan.py` + `intent.py`

**做什么**：

1. 调用 `IntentClassifier.classify()` 识别用户意图（Intent）
2. 判定 **接话模式（turn_mode）**：新话题 / 续问 / 致谢 / 换题
3. 映射 **任务类型（task_type）**，供 Gather/Compose prompt 参考
4. 确定 **焦点订单（focus_order_id）**（来自 EdgeContext 或跨轮记忆）
5. 设置短路标志：致谢时跳过 Gather 和 Compose LLM

**意图识别策略**（IntentClassifier）：

| 步骤 | 说明 |
|------|------|
| 1. 关键词规则 | `_KEYWORD_RULES` 优先匹配，置信度 ≥ 0.65 则直接命中 |
| 2. 接话判定 | 「谢谢/好的」→ acknowledgment；「那…呢」→ continuation |
| 3. 轻量 LLM | 模糊且 `INTENT_USE_LLM=true` 时，调 1 次小模型分类 |
| 4. 低置信兜底 | 无法路由 → `clarify` 澄清 |

**task_type 映射表**：

| task_type | 中文含义 | 典型触发 |
|-----------|----------|----------|
| `acknowledgment` | 致谢接话 | 「谢谢」「好的明白了」 |
| `chitchat` | 寒暄 | 「你好」「在吗」 |
| `clarify` | 需澄清 | 意图模糊 / unconfigured |
| `follow_up` | 续问 | turn_mode=continuation |
| `eligibility` | 资格判断 | 能否核销/能否预约/能否退款 |
| `lookup` | 信息查询 | 查订单/查券/查门店 |
| `policy` | 政策/投诉类 | 食品安全/申诉/补偿 |
| `complaint` | 投诉转人工 | 含「投诉」「人工」「客服」 |

**Plan 输出事件**：`context_ready` → Orchestrator 转为 `pipeline` SSE，前端更新意图与服务卡片。

**Plan 不做的事**：不决定 Gather 具体调哪些工具（交给 ReAct 模型）。

---

### 3.3 Gather — 有界 ReAct 核实（BoundedGatherReAct）

**文件**：`gather_react.py` + `gather_prompts.py`

**做什么**：在成稿之前，让模型**主动核实**业务事实与规则。这是「Observe + Diagnose」阶段的主体。

**执行流程**：

```text
1. 单订单 → 自动聚焦 focus_order_id
2. acknowledgment → 跳过 ReAct，直接 build_fact_sheet
3. Mock LLM 模式 → EvidenceGatherer 固定工具链（无 ReAct LLM）
4. Live 模式：
   a. 可选预取：AGENT_PREFETCH_FOCUS_BUNDLE=true 时程序先调 query_focus_bundle
   b. ReAct 循环（最多 AGENT_GATHER_MAX_STEPS=3 步）：
      每步 LLM 输出 JSON → thought / rules_to_check / action / action_input
   c. 终端动作：gather_complete（或兼容 finish）
   d. Gather 阶段禁止写操作（WRITE_TOOLS 返回 gate 错误）
   e. 只读工具不可重复（search_knowledge、run_diagnosis 除外）
5. 步数用尽 → 自动 gather_complete（auto_closed=True）
6. 多订单且无 focus → needs_clarify_focus=True，程序生成澄清文案
```

**ReAct 单步 JSON 字段**：

| 字段 | 中文说明 |
|------|----------|
| `thought` | 模型内心推理（推送到思考区） |
| `rules_to_check` | 本轮要核对的规则列表（如「须预约」「周末限定」） |
| `action` | 工具名或 `gather_complete` |
| `action_input` | 工具参数 |

**思考区推送**：每步 `thinking_token` SSE，内容经 `thinking_narrative._sanitize` 清洗（工具名中文化、剥离 Case 编号）。

**Mock 回退**（`evidence_gatherer.py`，无 LLM Key 时）：

- 多订单 → `list_orders`
- 有 focus → `query_focus_bundle`
- eligibility/follow_up/complaint → 可能加 `run_diagnosis`
- policy/complaint → 可能加 `search_knowledge`

---

### 3.4 fact_sheet — 事实表（程序抽取）

**文件**：`fact_sheet.py`

从 `tool_calls` + 诊断结果 + `service_context` **程序抽取**结构化事实，供 Compose 与 Verify 使用。模型不可编造 fact_sheet 之外的字段。

**典型字段**：

| 字段 | 含义 |
|------|------|
| `order_title` | 订单标题 |
| `order_status` | 订单状态（unused/scheduled/used 等） |
| `usage_rule` | 券面使用规则原文 |
| `needs_reservation` | 是否须预约（程序解析） |
| `has_reservation` | 是否已有预约记录 |
| `store_name` / `store_phone` | 门店信息 |
| `business_status` | 营业状态 |
| `diagnosis_case_id` | 诊断 Case（内部用，不展示给用户） |
| `can_refund` | 是否可退 |

---

### 3.5 Compose — 决策成稿（DecisionComposer）

**文件**：`decision_composer.py` + `compose_prompts.py`

**做什么**：**唯一成稿 LLM**。消费完整 Gather trace + fact_sheet + 跨轮记忆 + 规则块，输出结构化 JSON。

**Compose 输出 JSON 结构**：

| 字段 | 中文说明 |
|------|----------|
| `understanding.user_goal` | 用户真正想要什么 |
| `understanding.focus_entity` | 聚焦的订单/券/门店 |
| `reasoning.rule_application` | 规则如何适用（推送到思考区） |
| `reasoning.evidence_used` | 引用了哪些事实 |
| `self_check` | 自监督：是否回答了问题、有无编造 |
| `decision.mode` | reply / clarify / escalate 等 |
| `decision.focus_order_id` | 建议聚焦的订单 |
| `reply` | **给用户看的正式回复**（须含 emoji） |
| `suggested_actions` | 建议的可执行动作（按钮） |

**特殊路径**：

- **致谢接话**：`skip_compose_llm=true` → 模板 `_acknowledgment_reply`，**0 次 LLM**
- **校验失败**：`DecisionVerifier` 不通过 → 重试 Compose，最多 `AGENT_COMPOSE_MAX_RETRIES=1` 次

**Compose 后思考流**：`build_compose_thought_lines` → `thinking_token` SSE。

---

### 3.6 Verify — 程序校验（DecisionVerifier）

**文件**：`decision_verifier.py`

**注意**：Verify **不是独立 SSE 阶段**，嵌在 Compose 重试循环内，**不额外调用 LLM**。

**校验项**：

| 校验 | 说明 |
|------|------|
| reply 非空 | 必须有用户可见回复 |
| needs_clarify 一致性 | clarify 模式与 safe_to_send 不矛盾 |
| facts_used 一致性 | 引用的 fact 键应在 fact_sheet 内（宽松匹配） |
| **预约硬约束** | `needs_reservation=true` 时，禁止「无需预约/直接核销/查不到预约要求」等话术（正则拦截） |

校验失败 → Compose 重试；仍失败 → clarify 兜底文案。

---

### 3.7 Emit — 流式输出

**做什么**：

1. yield `agent` 事件（trace、finish、fact_sheet、compose_ms、pending_confirmations 等）
2. `ReplyPolisher.polish_stream()`：
   - `AGENT_TONE_POLISH_ENABLED=false` → 字符级假流式，直接输出 Compose 原文
   - `true` → 二次 LLM 语气润色 + 补 emoji
3. yield `token` → 正式回复逐字/词推送
4. yield `result` → 完整 `AgentRunResult` 供 Orchestrator 持久化

**多订单澄清短路**：`needs_clarify_focus` 时跳过 Compose，程序生成「请先告诉我要处理哪一笔」。

---

### 3.8 每轮 LLM 调用预算

| 阶段 | LLM 次数 | 条件 |
|------|----------|------|
| **Plan 意图** | 0~1 | 关键词置信度够高 → 0；模糊 → 1 |
| **Gather ReAct** | 0~3 | 致谢/mock → 0；每 ReAct 步 1 次 |
| **Compose 成稿** | 0~2 | 致谢模板 → 0；正常 1 次；校验失败 +1 |
| **Tone Polish 润色** | 0~1 | `AGENT_TONE_POLISH_ENABLED=true` 且回复够长 |
| **Error Recovery 兜底** | 0~1 | 主链路异常时 |

**典型场景合计**：

| 场景 | LLM 次数 |
|------|----------|
| 致谢「谢谢」 | **0** |
| 明确意图 + 1 步 Gather + Compose | **2** |
| 明确意图 + 3 步 Gather + Compose | **4** |
| 模糊意图 + LLM 分类 + 2 步 Gather + Compose | **4** |
| 上述 + Compose 重试 | **+1** |
| 上述 + Tone Polish 开启 | **+1** |

---

## 4. Agent 工具系统

**目录定义**：`tool_catalog.py`  
**执行器**：`agent_tools.py`  
**领域实现**：`tools.py`（LifeServiceTools）

### 4.1 只读工具（Gather 阶段可调用）

| 工具名 | 中文用途 | 典型场景 |
|--------|----------|----------|
| `list_orders` | 列出全部订单摘要 | 多订单未聚焦 |
| `query_order` | 订单详情/状态/可退性 | 查单 |
| `query_voucher` | 团购券/券码/规则 | 查券 |
| `query_store` | 门店地址/营业时间/电话 | 查门店 |
| `query_focus_bundle` | **推荐** 并行拉订单+券+门店 | 有焦点订单时优先 |
| `query_coupon` | 平台优惠券 | 优惠券问题 |
| `query_refund` | 售后/退款进度 | 退款查询 |
| `query_ticket` | 工单进度 | 投诉跟进 |
| `search_knowledge` | 知识库 FAQ/政策检索 | 规则解释 |
| `run_diagnosis` | 触发 SDS 诊断引擎 | 核销失败/资格判断 |

### 4.2 写操作工具（Gather 禁止；需用户确认）

| 工具名 | 中文用途 | 前端 action_id |
|--------|----------|----------------|
| `regenerate_qr` | 重新生成核销码 | regenerate_qr |
| `contact_merchant` | 联系商家 | contact_merchant |
| `create_reservation` | 创建预约 | create_reservation |
| `apply_refund` | 提交退款 | apply_refund |
| `human_handoff` | 转人工建工单 | human_handoff |

写操作未确认时返回 `pending_confirmation`；Compose 输出 `suggested_actions`；用户在前端 `ActionSheet` 确认后，走 `POST /api/v1/workflow/actions`。

### 4.3 工具裁剪策略

- 按 **Intent** 裁剪可用工具集（`_INTENT_TOOL_SETS`）
- `AGENT_HIDE_ATOMIC_FOCUS_READS=true` 时，有 `query_focus_bundle` 则隐藏分散的 `query_order/query_voucher/query_store`
- `AGENT_COALESCE_FOCUS_READS=true` 时，原子读合并到 bundle

---

## 5. SDS v1 诊断系统

**定位**：Structured Diagnostic System，结构化诊断系统。读 DB 客观事实 + 用户话术，输出 Case 与推荐动作。**不直接写用户回复**，仅供 Agent 参考（advisory）。

```text
Intent 意图
  → DiagnosisContext 诊断上下文（订单/券/门店/用户原话）
  → 诊断树逐步校验（营业时段、预约、跨店、POS 同步…）
  → CaseDiagnosisResult（case_id, case_name, diagnosis[], solution[]）
  → slim 后注入 Gather observation / Compose prompt
```

**规模**：`case_specs.py` 中 **73** 个注册 Case

| 类别前缀 | 中文含义 | 示例 |
|----------|----------|------|
| IC | Information Check 信息核对 | 订单/券基础校验 |
| PC | Policy Check 规则校验 | PC-008 跨店、PC-009 时段、PC-010 缺预约 |
| FC | Fulfillment Check 履约校验 | FC-001 闭店、FC-006 拒核销、FC-008 POS 未同步 |
| AC | Action Check 动作校验 | 退款/预约资格 |
| CC | Complaint Check 投诉类 | 安全/品质投诉 |

**典型推理示例**（库中无 Case 标签，运行时推导）：

| Case | 依据事实 |
|------|----------|
| PC-008 跨店 | `order.store_id ≠ voucher.store_id` |
| PC-009 时段 | `usage_rule` 含「仅限周末」+ 当前非周末 |
| PC-010 缺预约 | 规则须预约 + 订单无 `reservation_confirmed` |
| FC-001 暂停营业 | `business_status = suspended` |
| FC-006 商家拒核销 | 券有效 + 用户描述「老板不给用」 |

**调用路径**：Gather ReAct 选 `run_diagnosis` → `AgentToolExecutor` → `DiagnosisEngine.diagnose()`

**API**：`GET /api/v1/diagnosis/cases` 可浏览全部 Case 规格。

---

## 6. 意图空间（Intent Space）

**文件**：`intent.py` — `INTENT_CATALOG`

共 **27** 个可路由意图（含 chitchat/clarify/unconfigured）：

| Intent | 中文说明 |
|--------|----------|
| QueryOrder | 查询订单状态、支付、详情 |
| QueryVoucher | 查询团购券/券码/有效期 |
| QueryCoupon | 查询平台优惠券 |
| QueryStore | 查询门店地址/营业时间/电话 |
| QueryReservation | 查询预约状态/如何预约 |
| QueryRefund | 查询退款/售后进度 |
| QueryTicket | 查询工单进度 |
| CheckVoucherAvailability | 判断券能不能用、资格校验 |
| CheckRefundEligibility | 判断能不能退款 |
| CheckReservationEligibility | 判断能不能预约 |
| VoucherUnavailable | 券用不了、核销失败、扫不出来 |
| ReservationFailure | 预约失败、约不上 |
| MerchantReject | 商家拒绝核销/接待 |
| StoreUnavailable | 门店关门、暂停营业、搬迁 |
| ServiceMismatch | 套餐缩水、服务不符、强制消费 |
| RefundRequest | 申请退款 |
| CompensationRequest | 申请补偿 |
| AppealRequest | 申诉 |
| MerchantComplaint | 投诉商家违规 |
| ServiceComplaint | 投诉服务质量 |
| SafetyComplaint | 食品安全、人身安全 |
| PriceDispute | 价格争议 |
| HumanTransfer | 转人工 |

`ACTIONABLE_INTENTS`：可进入诊断引擎的意图子集。

---

## 7. SSE 流式协议

**入口**：`POST /api/v1/chat/stream` → `EventSourceResponse`（`routers/chat.py`）

| event 事件名 | 来源 | payload 要点 | 前端处理 |
|--------------|------|--------------|----------|
| `pipeline` | Orchestrator | intent、pipeline.steps、service_cards、focus_order_id | 更新卡片/焦点/链路步骤 |
| `gather_step` | Pipeline | step、phase、step_ms | 后端 profiling 用；主 UI 未订阅 |
| `thinking_token` | Gather/Compose | `{ text }` | **思考区逐字追加** |
| `thinking` | ErrorRecovery | `{ line }` | 整行追加（兜底场景） |
| `token` | Emit | `{ text }` | **正式回复流式追加** |
| `done` | Orchestrator | reply、tool_calls、pending_confirmations、agent_finish | 落盘消息、写操作确认 |
| `error` | Recovery | `{ message }` | 错误提示 |

**前端流式阶段**（`App.tsx`）：

```text
streamPhase:
  observing  → 思考区活跃（ThinkingStream 灰字）
  replying   → 正式气泡流式输出；思考区 compact 缩小
```

**EdgeContext**（前端打包发给后端）：

| 字段 | 说明 |
|------|------|
| `user_id` | 当前 Demo 用户 |
| `focus_order_id` | 焦点订单 |
| `city` | 城市（授权后） |
| `recent_order_ids` | 近期订单 ID |
| `local_voucher_summary` | 券摘要 |
| `behavior_tags` | 行为标签 |
| `location_permission` | 位置授权开关 |

---

## 8. 思考流与跨轮记忆

### 8.1 thinking_stream.py

- `stream_thinking_line` / `stream_thinking_lines`：按字/词切分，带 `asyncio.sleep` 节奏
- SSE 类型：`thinking_token`

### 8.2 thinking_narrative.py

| 函数 | 作用 |
|------|------|
| `_sanitize` | 替换工具英文名、剥离 Case 编号、Intent 转中文 |
| `format_tool_observation_thought` | 工具结果 → 用户可读事实句 |
| `build_gather_react_thought_lines` | Gather trace → 思考段落 |
| `build_compose_thought_lines` | Compose JSON → 理解/推理段落 |
| `build_plan_thought_lines` | **故意返回空**（Plan 不输出套话） |

### 8.3 conversation_memory.py

Redis 持久化（`build_agent_context`），下轮 Gather/Compose 通过 `format_memory_block()` 注入：

| 字段 | 说明 |
|------|------|
| `focus_order_id` | 焦点订单 |
| `intent` | 上轮意图 |
| `digest` | 工具调用摘要 |
| `fact_sheet` | 紧凑事实表 |
| `gather_summary` | Gather 结束摘要 |
| `rules_checked` | 已核对规则 |
| `last_reply` | 上轮回复 |
| `tool_names` | 已调用工具名 |

---

## 9. 前端架构

### 9.1 主界面结构（App.tsx）

```text
PhoneShell 手机壳
├── Header
│   ├── 产品名 + LLM 模式指示
│   └── DemoUserSwitcher（120 用户 / 随机 10 人展示）
├── ConversationView 主会话区
│   ├── OrderFocusPanel（多订单焦点切换）
│   ├── 消息气泡（user / assistant）
│   ├── ThinkingStream（思考区 · 灰字流）
│   ├── 流式 assistant 气泡
│   ├── ServiceCards / Workflow 动作按钮
│   └── 输入框 + QUICK_PROMPTS 快捷话术
├── BottomSheet（+ 半屏菜单）
│   ├── order / orders — 订单详情与历史
│   ├── fulfillment — 履约时间线
│   ├── actions — 操作记录
│   └── settings — PrivacySettings 隐私授权
└── ActionSheet — 写操作确认（退款/预约/转人工）
```

### 9.2 关键组件

| 组件 | 文件 | 作用 |
|------|------|------|
| ThinkingStream | `components/ThinkingStream.tsx` | 段落灰字 + 光标动画 |
| thinkingReveal | `lib/thinkingReveal.ts` | 跟显（后端已带节奏） |
| DemoUserSwitcher | `components/DemoUserSwitcher.tsx` | 用户切换 / 换一批 |
| OrderFocusPanel | `components/OrderFocusPanel.tsx` | 多订单聚焦 |
| ServicePanels | `components/ServicePanels.tsx` | 时间线 + 操作记录 |
| FulfillmentContextCard | `components/FulfillmentContextCard.tsx` | 履约上下文卡片 |
| PipelinePanel | `components/PipelinePanel.tsx` | 链路步骤（调试用） |

---

## 10. 数据模型

| 表名 | 中文说明 |
|------|----------|
| `users` | C 端用户 |
| `merchant_stores` | 门店 POI（`supports_reservation`、`business_status`、metadata） |
| `life_orders` | 生活服务订单 + metadata（预约记录等） |
| `vouchers` | 团购券 + **usage_rule 文案** |
| `coupons` | 平台优惠券 |
| `refund_cases` | 退款/售后单 |
| `fulfillment_events` | 履约事件时间线 |
| `knowledge_articles` | 平台知识库 |
| `conversation_events` | 对话与工具日志 |

**重要原则**：库中**无**诊断 Case 标签；仅客观业务事实。

---

## 11. Mock 数据机制

### 11.1 生成

`scripts/generate_mock_data.py` → `deploy/init-db/03-bulk-seed.sql`

| 维度 | 说明 |
|------|------|
| 用户规模 | 120 人：`user_001` ~ `user_120` |
| 正常样本 | 001~080：覆盖下单/预约/核销/过期/退款全阶段 |
| 异常样本 | 081~120：客观事实预埋，Case 运行时推理 |
| 预约策略 | 约一半门店 `must_reserve`，一半 `walk_in` |
| 时间基准 | `SEED_ANCHOR = 2026-01-15` 相对偏移 |

### 11.2 启动 Bootstrap

`db/bulk_bootstrap.py` + `db/mock_time_shift.py`：

1. Schema migrate
2. 知识库 seed
3. **`ensure_bulk_seed`**：用户 < 100 或 `bulk_seed_version < 6` → truncate 并重灌
4. **`shift_mock_timestamps`**：业务时间平移到当前时刻

当前版本：**bulk_seed_version = 6**

### 11.3 Demo 用户 UI

- 库内 120 人；UI 每次随机展示 **10 人**（`SAMPLE_SIZE=10`）
- API：`GET /api/v1/users/sample?count=10`
- 切换用户 → 重新 bootstrap（welcome + 新 session + 清空对话）

---

## 12. 配置参考

### 12.1 Pipeline 相关

| 环境变量 | .env.example | config.py 默认 | 说明 |
|----------|--------------|----------------|------|
| `AGENT_GATHER_MAX_STEPS` | 3 | 3 | Gather ReAct 步数上限 |
| `AGENT_GATHER_TEMPERATURE` | 0.2 | 0.2 | Gather LLM 温度 |
| `AGENT_GATHER_MAX_TOKENS` | 512 | 512 | Gather LLM token |
| `AGENT_PREFETCH_FOCUS_BUNDLE` | true | true | 程序预拉 bundle |
| `AGENT_COMPOSE_MAX_TOKENS` | 768 | 768 | Compose token |
| `AGENT_COMPOSE_MAX_RETRIES` | 1 | 1 | Verify 失败重试次数 |
| `AGENT_TONE_POLISH_ENABLED` | **false** | **true** | 二次润色；以 .env 为准 |
| `AGENT_HISTORY_MAX_TURNS` | 4 | 4 | 上下文轮数 |
| `AGENT_FAST_TURN_ENABLED` | false | false | **已废弃** |

### 12.2 意图识别

| 环境变量 | 默认 | 说明 |
|----------|------|------|
| `INTENT_CONFIDENCE_THRESHOLD` | 0.65 | 高于此不调 LLM |
| `INTENT_USE_LLM` | true | 模糊时启用 LLM 分类 |

### 12.3 LLM

| 环境变量 | 说明 |
|----------|------|
| `LLM_API_KEY` | 火山方舟等 OpenAI 兼容 Key |
| `LLM_BASE_URL` | API 地址 |
| `LLM_MODEL` | 模型 ID |
| `LLM_REQUIRE_LIVE` | true = 无 Key 报错（不静默 Mock） |

---

## 13. 部署拓扑

| 服务 | 端口 | 说明 |
|------|------|------|
| `web` | 5173→80 | Nginx 静态 + API 反代 |
| `api` | 8000 | FastAPI（不对公网开放） |
| `postgres` | 5432 | 领域数据（不对公网开放） |
| `redis` | 6379 | 会话（不对公网开放） |

详见 [DEPLOY_ALIYUN.md](./DEPLOY_ALIYUN.md)。

---

## 14. 异常处理

| 层级 | 行为 |
|------|------|
| 工具异常 | 返回结构化 `clues`，Gather 写入 trace |
| Compose 校验失败 | 重试 Compose；仍失败 → clarify 兜底 |
| 主链路崩溃 | `ErrorRecoveryService` 将上下文交给 LLM 生成可读回复 |
| 多订单未聚焦 | 程序 clarify，不进入 Compose |

不向用户暴露 Python 堆栈或内部术语。

---

## 15. 扩展方向（非 P0）

- 真实生活服务 Open API 对接
- 向量检索知识库（当前为关键词检索）
- 工单坐席端、OpenTelemetry 可观测性
- 门店适用列表独立表
- 多模态（图片识别券码/小票）

---

## 16. 关键模块速查

| 模块 | 路径 |
|------|------|
| 统一 Pipeline | `apps/api/app/services/unified_turn_pipeline.py` |
| Turn 规划 | `apps/api/app/services/turn_plan.py` |
| 意图识别 | `apps/api/app/services/intent.py` |
| Gather ReAct | `apps/api/app/services/gather_react.py` |
| Compose 成稿 | `apps/api/app/services/decision_composer.py` |
| 程序校验 | `apps/api/app/services/decision_verifier.py` |
| 工具目录 | `apps/api/app/services/tool_catalog.py` |
| 工具执行 | `apps/api/app/services/agent_tools.py` |
| 事实表 | `apps/api/app/services/fact_sheet.py` |
| 思考 SSE | `apps/api/app/services/thinking_stream.py` |
| 思考文案 | `apps/api/app/services/thinking_narrative.py` |
| 跨轮记忆 | `apps/api/app/services/conversation_memory.py` |
| 诊断引擎 | `apps/api/app/diagnosis/engine.py` |
| SSE 路由 | `apps/api/app/routers/chat.py` |
| 编排层 | `apps/api/app/services/orchestrator.py` |
| 前端主界面 | `apps/web/src/App.tsx` |
| SSE 客户端 | `apps/web/src/api/client.ts` |

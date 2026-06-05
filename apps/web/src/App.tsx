import { useCallback, useEffect, useMemo, useState } from "react";
import { buildEdgeContext, createRefund, createSession, executeWorkflowAction, fetchHealth, fetchOperationLogs, fetchServiceContext, streamChat } from "./api/client";
import { ActionSheet } from "./components/ActionSheet";
import { BottomSheet } from "./components/BottomSheet";
import { PhoneShell } from "./components/PhoneShell";
import { PrivacySettings } from "./components/PrivacySettings";
import type { Message, PipelineStep, PrivacySettings as Settings, ServiceCard, ServiceContext, ToolCall, WorkflowDiagnosis, WorkflowSolution } from "./types";

type Page = "home" | "order" | "fulfillment" | "settings" | "actions";

const DEFAULT_SETTINGS: Settings = {
  order_access: true,
  voucher_access: true,
  coupon_access: true,
  location_access: true,
  behavior_summary: true,
  stream_response: true,
};

const QUICK_PROMPTS = ["查看券码", "到店核销失败，扫不出来", "联系商家", "我要退款"];

const SHEET_TITLES: Record<Exclude<Page, "home">, string> = {
  order: "订单与券码",
  fulfillment: "履约详情",
  settings: "授权设置",
  actions: "操作记录",
};

const journey = [
  ["发现团购", "川巷子火锅双人餐"],
  ["购买订单", "已支付 ¥168"],
  ["预约", "建议提前 2 小时"],
  ["到店", "望京店营业中"],
  ["核销", "当前异常待处理"],
  ["消费", "解决后完成"],
  ["售后", "退款/投诉/人工"],
];

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

function text(value: unknown, fallback = "-") {
  return value == null ? fallback : String(value);
}

export default function App() {
  const [page, setPage] = useState<Page>("home");
  const [settings, setSettings] = useState<Settings>(() => {
    const saved = localStorage.getItem("douyin-life-settings");
    return saved ? JSON.parse(saved) : DEFAULT_SETTINGS;
  });
  const edge = useMemo(() => buildEdgeContext(settings), [settings]);
  const [context, setContext] = useState<ServiceContext | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: uid(),
      role: "assistant",
      content: "我会陪你完成这次火锅套餐履约。现在看到你有一张待核销团购券，到店后可直接让我处理核销问题。",
    },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [pipeline, setPipeline] = useState<PipelineStep[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [workflow, setWorkflow] = useState<WorkflowDiagnosis | null>(null);
  const [operationLogs, setOperationLogs] = useState<Array<Record<string, unknown>>>([]);
  const [serviceCards, setServiceCards] = useState<ServiceCard[]>([]);
  const [refundOrderId, setRefundOrderId] = useState<string | null>(null);
  const [verificationCodeVersion, setVerificationCodeVersion] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [llmMode, setLlmMode] = useState("—");

  useEffect(() => {
    localStorage.setItem("douyin-life-settings", JSON.stringify(settings));
  }, [settings]);

  useEffect(() => {
    fetchHealth().then((h) => setLlmMode(h.llm_mode)).catch(() => setLlmMode("offline"));
    fetchServiceContext().then(setContext).catch(() => setError("服务上下文读取失败"));
    createSession(edge).then((s) => setSessionId(s.session_id)).catch(() => setError("会话创建失败"));
  }, []);

  const refreshContext = useCallback(() => {
    fetchServiceContext().then(setContext).catch(() => setError("刷新上下文失败"));
  }, []);

  const send = useCallback(
    async (raw: string) => {
      const content = raw.trim();
      if (!content || streaming) return;
      setInput("");
      setError(null);

      let sid = sessionId;
      if (!sid) {
        const session = await createSession(edge);
        sid = session.session_id;
        setSessionId(sid);
      }

      setMessages((items) => [...items, { id: uid(), role: "user", content }]);
      setStreaming(true);
      setPipeline([]);

      const assistantId = uid();
      let reply = "";
      await streamChat(sid, content, edge, {
        onPipeline: (payload) => {
          setPipeline(payload.pipeline.steps ?? []);
          setServiceCards((payload.service_cards ?? []) as ServiceCard[]);
        },
        onToken: (token) => {
          reply += token;
          setMessages((items) => {
            const rest = items.filter((item) => item.id !== assistantId);
            return [...rest, { id: assistantId, role: "assistant", content: reply }];
          });
        },
        onDone: (data) => {
          setPipeline(((data.pipeline as { steps?: PipelineStep[] })?.steps ?? []) as PipelineStep[]);
          setServiceCards((data.service_cards ?? []) as ServiceCard[]);
          setToolCalls((data.tool_calls ?? []) as ToolCall[]);
          if (data.workflow) setWorkflow(data.workflow as WorkflowDiagnosis);
          fetchOperationLogs("user_demo", sid).then((res) => setOperationLogs(res.logs ?? [])).catch(() => undefined);
          setMessages((items) => {
            const rest = items.filter((item) => item.id !== assistantId);
            return [
              ...rest,
              {
                id: assistantId,
                role: "assistant",
                content: text(data.reply, reply),
                intent: text(data.intent, ""),
                pipeline: data.pipeline as Message["pipeline"],
                service_cards: (data.service_cards ?? []) as ServiceCard[],
                tool_calls: (data.tool_calls ?? []) as ToolCall[],
              },
            ];
          });
          setStreaming(false);
        },
        onError: (err) => {
          setError(err.message);
          setStreaming(false);
        },
      });
    },
    [edge, sessionId, streaming]
  );

  const hotpotOrder = context?.orders.find((order) => text(order.id) === "order_hotpot_8821") ?? context?.orders[0];
  const hotpotVoucher = context?.vouchers.find((voucher) => text(voucher.id) === "voucher_hotpot_8821") ?? context?.vouchers[0];
  const activeCards = serviceCards.length ? serviceCards : buildDefaultCards(context);

  const submitRefund = async () => {
    if (!refundOrderId || !sessionId) return;
    const result = await createRefund(sessionId, refundOrderId, "用户在履约服务管家中发起退款");
    setRefundOrderId(null);
    setMessages((items) => [
      ...items,
      { id: uid(), role: "assistant", content: `退款申请已提交，售后单 ${result.id}，我会继续跟进处理进度。` },
    ]);
    refreshContext();
  };

  const runWorkflowAction = async (actionId: string, title: string) => {
    if (!sessionId) return;
    try {
      const result = await executeWorkflowAction(
        sessionId,
        actionId,
        hotpotOrder?.id ? String(hotpotOrder.id) : undefined,
        hotpotVoucher?.id ? String(hotpotVoucher.id) : undefined
      );
      if (actionId === "regenerate_qr") setVerificationCodeVersion((value) => value + 1);
      setMessages((items) => [
        ...items,
        {
          id: uid(),
          role: "assistant",
          content: formatActionResult(actionId, title, result),
        },
      ]);
      fetchOperationLogs("user_demo", sessionId).then((res) => setOperationLogs(res.logs ?? [])).catch(() => undefined);
      refreshContext();
    } catch {
      setError(`执行「${title}」失败，请稍后重试`);
    }
  };

  const regenerateCode = () => runWorkflowAction("regenerate_qr", "重新生成核销码");

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0f0f10] px-3 py-4 text-slate-950">
      <PhoneShell>
        <HomePage
          context={context}
          order={hotpotOrder}
          voucher={hotpotVoucher}
          messages={messages}
          streaming={streaming}
          input={input}
          error={error}
          cards={activeCards}
          llmMode={llmMode}
          workflow={workflow}
          onInput={setInput}
          onSend={send}
          onNavigate={setPage}
          onRefund={setRefundOrderId}
          onRegenerate={regenerateCode}
          onWorkflowAction={runWorkflowAction}
          verificationCodeVersion={verificationCodeVersion}
        />

        <BottomSheet
          title={page === "home" ? "" : SHEET_TITLES[page]}
          open={page !== "home"}
          onClose={() => setPage("home")}
        >
          <DetailContent
            page={page === "home" ? "order" : page}
            context={context}
            order={hotpotOrder}
            voucher={hotpotVoucher}
            settings={settings}
            pipeline={pipeline}
            toolCalls={toolCalls}
            operationLogs={operationLogs}
            onToggle={(key) => setSettings((current) => ({ ...current, [key]: !current[key] }))}
            onSend={send}
            onRefund={setRefundOrderId}
            onWorkflowAction={runWorkflowAction}
          />
        </BottomSheet>

        {refundOrderId && (
          <ActionSheet
            title="确认申请退款"
            description="系统会基于订单状态、券核销情况和商家规则创建售后单。当前 Demo 会写入本地数据库。"
            primaryText="提交退款"
            onPrimary={submitRefund}
            onClose={() => setRefundOrderId(null)}
          />
        )}
      </PhoneShell>
    </div>
  );
}

function HomePage({
  context,
  order,
  voucher,
  messages,
  streaming,
  input,
  error,
  cards,
  llmMode,
  workflow,
  verificationCodeVersion,
  onInput,
  onSend,
  onNavigate,
  onRefund,
  onRegenerate,
  onWorkflowAction,
}: {
  context: ServiceContext | null;
  order?: Record<string, unknown>;
  voucher?: Record<string, unknown>;
  messages: Message[];
  streaming: boolean;
  input: string;
  error: string | null;
  cards: ServiceCard[];
  llmMode: string;
  workflow: WorkflowDiagnosis | null;
  verificationCodeVersion: number;
  onInput: (value: string) => void;
  onSend: (value: string) => void;
  onNavigate: (page: Page) => void;
  onRefund: (orderId: string) => void;
  onRegenerate: () => void;
  onWorkflowAction: (actionId: string, title: string) => void;
}) {
  const solutions = workflow?.solution ?? [
    { action_id: "regenerate_qr", title: "重新生成核销码", description: "", tool: "" },
    { action_id: "contact_merchant", title: "联系商家", description: "", tool: "" },
    { action_id: "manual_code", title: "展示券码手动核销", description: "", tool: "" },
    { action_id: "human_handoff", title: "转人工", description: "", tool: "" },
  ];
  return (
    <>
      <header className="shrink-0 bg-[#111] px-4 pb-3 pt-2 text-white">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[11px] text-white/50">抖音生活服务</div>
            <div className="text-lg font-bold">AI履约服务管家</div>
            <div className="mt-0.5 text-[10px] text-white/45">会话服务在线 · LLM {llmMode}</div>
          </div>
          <button
            type="button"
            onClick={() => onNavigate("settings")}
            className="rounded-full border border-white/10 bg-white/10 px-3 py-1.5 text-xs"
          >
            设置
          </button>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto bg-[#f5f5f5] px-3 py-3">
        <section className="rounded-[22px] bg-white p-4 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[11px] font-semibold text-[#fe2c55]">当前履约中</div>
              <h2 className="mt-1 text-lg font-bold">{text(order?.title, "川巷子火锅双人餐")}</h2>
              <p className="mt-1 text-xs text-slate-500">
                {text(context?.user.display_name, "小林")} · {text(context?.user.city, "北京")} · 待到店核销
              </p>
            </div>
            <span className="rounded-full bg-[#fff1f3] px-2.5 py-1 text-[11px] font-semibold text-[#fe2c55]">待核销</span>
          </div>
          <div className="mt-4 grid grid-cols-3 gap-2">
            <Metric label="实付" value={`¥${text(order?.paid_amount, "168")}`} />
            <Metric label="券码" value={text(voucher?.code, "DY8821")} />
            <Metric label="核销码" value={`v${verificationCodeVersion}`} />
          </div>
          <div className="mt-4 grid grid-cols-4 gap-2">
            <ActionButton label="订单" onClick={() => onNavigate("order")} />
            <ActionButton label="履约详情" onClick={() => onNavigate("fulfillment")} />
            <ActionButton label="操作记录" onClick={() => onNavigate("actions")} />
            <ActionButton label="退款" onClick={() => order?.id && onRefund(String(order.id))} />
          </div>
        </section>

        <section className="mt-3 rounded-[22px] bg-white p-3 shadow-sm">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-sm font-bold">履约进度</div>
            <button type="button" className="text-xs text-[#fe2c55]" onClick={() => onNavigate("fulfillment")}>
              查看详情
            </button>
          </div>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {journey.map(([title, desc], index) => (
              <div
                key={title}
                className={`min-w-[86px] rounded-2xl border p-2 ${
                  index < 4
                    ? "border-emerald-100 bg-emerald-50"
                    : index === 4
                      ? "border-[#fe2c55]/20 bg-[#fff1f3]"
                      : "border-slate-100 bg-slate-50"
                }`}
              >
                <div className="text-xs font-bold">{title}</div>
                <div className="mt-1 text-[10px] leading-snug text-slate-500">{desc}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-3 rounded-[22px] bg-white p-3 shadow-sm">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-sm font-bold">会话服务</div>
            <span className="text-[10px] text-slate-400">多轮自然语言</span>
          </div>
          <div className="space-y-2">
            {messages.map((message) => (
              <div key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[86%] rounded-2xl px-3 py-2 text-sm leading-relaxed ${
                    message.role === "user" ? "bg-[#111] text-white" : "bg-slate-100 text-slate-900"
                  }`}
                >
                  {message.content}
                </div>
              </div>
            ))}
            {streaming && <div className="text-xs text-slate-500">AI 正在观察履约状态并调用工具...</div>}
            {error && <div className="rounded-xl bg-red-50 px-3 py-2 text-xs text-red-600">{error}</div>}
          </div>
          <div className="mt-3 flex gap-2 overflow-x-auto">
            {QUICK_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => onSend(prompt)}
                className="shrink-0 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-700"
              >
                {prompt}
              </button>
            ))}
          </div>
        </section>

        <section className="mt-3 rounded-[22px] bg-white p-3 shadow-sm">
          <div className="mb-2 text-sm font-bold">AI建议行动</div>
          {workflow?.root_cause && (
            <div className="mb-2 rounded-xl bg-[#fff1f3] px-3 py-2 text-xs text-[#fe2c55]">
              诊断根因：{workflow.root_cause}（置信度 {workflow.confidence ?? "—"}）
            </div>
          )}
          <div className="grid grid-cols-2 gap-2">
            {solutions.slice(0, 4).map((item) => (
              <button
                key={item.action_id}
                type="button"
                onClick={() =>
                  item.action_id === "human_handoff"
                    ? onSend("帮我转人工")
                    : onWorkflowAction(item.action_id, item.title)
                }
                className="rounded-2xl bg-slate-100 px-3 py-2 text-xs font-semibold"
              >
                {item.title}
              </button>
            ))}
          </div>
        </section>

        <section className="mt-3 space-y-2">
          {cards.slice(0, 2).map((card, index) => (
            <button
              key={`${card.type}-${index}`}
              type="button"
              onClick={() => onNavigate(card.type === "order" || card.type === "voucher" ? "order" : "actions")}
              className="w-full rounded-[20px] bg-white p-3 text-left shadow-sm"
            >
              <div className="text-[10px] font-semibold text-[#fe2c55]">{card.type}</div>
              <div className="mt-1 text-sm font-bold">{card.title}</div>
              <div className="mt-1 text-xs text-slate-500">{card.status}</div>
            </button>
          ))}
        </section>
      </main>

      <footer className="shrink-0 border-t border-slate-100 bg-white p-3">
        <div className="flex gap-2">
          <input
            className="flex-1 rounded-full bg-slate-100 px-4 py-2.5 text-sm outline-none"
            placeholder="直接描述你的履约问题..."
            value={input}
            onChange={(event) => onInput(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && onSend(input)}
            disabled={streaming}
          />
          <button
            type="button"
            onClick={() => onSend(input)}
            disabled={streaming}
            className="h-10 w-10 rounded-full bg-[#fe2c55] text-white disabled:opacity-50"
            aria-label="发送"
          >
            ↑
          </button>
        </div>
      </footer>
    </>
  );
}

function DetailContent({
  page,
  context,
  order,
  voucher,
  settings,
  pipeline,
  toolCalls,
  operationLogs,
  onToggle,
  onSend,
  onRefund,
  onWorkflowAction,
}: {
  page: Exclude<Page, "home">;
  context: ServiceContext | null;
  order?: Record<string, unknown>;
  voucher?: Record<string, unknown>;
  settings: Settings;
  pipeline: PipelineStep[];
  toolCalls: ToolCall[];
  operationLogs: Array<Record<string, unknown>>;
  onToggle: (key: keyof Settings) => void;
  onSend: (value: string) => void;
  onRefund: (orderId: string) => void;
  onWorkflowAction: (actionId: string, title: string) => void;
}) {
  if (page === "settings") {
    return <PrivacySettings settings={settings} onToggle={onToggle} />;
  }

  return (
    <div className="space-y-3 pb-4">
          {page === "order" && (
            <div className="space-y-3">
              <InfoCard title="订单信息" rows={[
                ["商品", text(order?.title)],
                ["状态", text(order?.status)],
                ["实付", `¥${text(order?.paid_amount)}`],
                ["是否可退", order?.can_refund ? "支持退款" : "暂不支持"],
              ]} />
              <InfoCard title="团购券" rows={[
                ["券码", text(voucher?.code)],
                ["状态", text(voucher?.status)],
                ["有效期", text(voucher?.valid_to)],
                ["规则", text(voucher?.usage_rule)],
              ]} />
              {order?.id != null && (
                <button
                  type="button"
                  onClick={() => onRefund(String(order.id))}
                  className="w-full rounded-2xl bg-[#fe2c55] py-3 text-sm font-semibold text-white"
                >
                  申请退款
                </button>
              )}
            </div>
          )}
          {page === "fulfillment" && (
            <div className="space-y-3">
              {journey.map(([name, desc], index) => (
                <div key={name} className="rounded-2xl bg-white p-3">
                  <div className="flex items-center gap-3">
                    <span className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${index <= 4 ? "bg-[#fe2c55] text-white" : "bg-slate-100"}`}>
                      {index + 1}
                    </span>
                    <div>
                      <div className="text-sm font-bold">{name}</div>
                      <div className="text-xs text-slate-500">{desc}</div>
                    </div>
                  </div>
                </div>
              ))}
              <button type="button" onClick={() => onSend("到店核销失败，扫不出来")} className="w-full rounded-2xl bg-[#111] py-3 text-sm font-semibold text-white">
                让 AI 诊断核销失败
              </button>
              <button type="button" onClick={() => onWorkflowAction("regenerate_qr", "重新生成核销码")} className="w-full rounded-2xl bg-[#fe2c55] py-3 text-sm font-semibold text-white">
                重新生成核销码
              </button>
            </div>
          )}
          {page === "actions" && (
            <>
              <OperationRecords pipeline={pipeline} toolCalls={toolCalls} operationLogs={operationLogs} />
              <InfoCard title="用户上下文" rows={[
                ["用户", text(context?.user.display_name)],
                ["城市", text(context?.user.city)],
                ["订单数", String(context?.orders.length ?? 0)],
                ["券包数", String((context?.vouchers.length ?? 0) + (context?.coupons.length ?? 0))],
              ]} />
            </>
          )}
    </div>
  );
}

function OperationRecords({
  pipeline,
  toolCalls,
  operationLogs,
}: {
  pipeline: PipelineStep[];
  toolCalls: ToolCall[];
  operationLogs: Array<Record<string, unknown>>;
}) {
  const persisted = operationLogs.map((log) => ({
    actor: actorLabel(String(log.actor)),
    title: String(log.summary ?? log.operation_type),
    detail: JSON.stringify(log.payload ?? {}).slice(0, 120),
    tone: String(log.actor ?? "agent"),
  }));
  const records = [
    ...persisted.slice(0, 8),
    ...pipeline.map((step) => ({
      actor: "智能体",
      title: stepName(step.name),
      detail: step.detail || "已完成",
      tone: "agent",
    })),
    ...toolCalls.map((call) => ({
      actor: "系统工具",
      title: toolName(call.name),
      detail: toolSummary(call.result),
      tone: "tool",
    })),
  ];

  return (
    <div className="rounded-[22px] bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-bold">操作明细</div>
          <div className="mt-1 text-xs text-slate-500">展示用户与智能体在本次履约服务中的关键动作</div>
        </div>
        <span className="rounded-full bg-[#fff1f3] px-2 py-1 text-[10px] font-semibold text-[#fe2c55]">
          {records.length} 条
        </span>
      </div>
      <div className="mt-4 space-y-3">
        {records.map((record, index) => (
          <div key={`${record.actor}-${record.title}-${index}`} className="flex gap-3">
            <div className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${dotClass(record.tone)}`} />
            <div className="flex-1 border-b border-slate-100 pb-3 last:border-b-0">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold text-slate-400">{record.actor}</span>
                <span className="text-[10px] text-slate-400">{index + 1}</span>
              </div>
              <div className="mt-1 text-sm font-bold">{record.title}</div>
              <div className="mt-1 text-xs leading-relaxed text-slate-500">{record.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function dotClass(tone: string) {
  if (tone === "user") return "bg-[#111]";
  if (tone === "tool") return "bg-[#fe2c55]";
  return "bg-emerald-500";
}

function stepName(name: string) {
  const names: Record<string, string> = {
    intent_detect: "理解用户意图",
    workflow_match: "匹配处置流程",
    service_context: "观察履约上下文",
    knowledge_search: "检索服务知识",
    tool_action: "选择业务工具",
    prompt_build: "组织回复依据",
    model_response: "生成服务解释",
  };
  return names[name] ?? name;
}

function toolName(name: string) {
  const names: Record<string, string> = {
    query_order: "查询订单",
    query_voucher: "查询团购券",
    query_coupon: "查询优惠券",
    query_store: "查询门店",
    query_refund: "查询售后规则",
    create_refund_case: "创建退款申请",
    create_service_ticket: "创建服务工单",
    transfer_to_human: "转人工",
    diagnose_voucher_issue: "诊断核销失败",
  };
  return names[name] ?? name;
}

function toolSummary(result: unknown) {
  if (!result) return "无返回";
  const raw = JSON.stringify(result);
  if (raw.includes("voucher_verification_failed")) return "确认券未使用、未过期、适用当前门店；疑似商家扫码设备未同步券状态。";
  if (raw.includes("DY8821-2468")) return "读取到火锅双人餐券码 DY8821-2468，可用于手动核销。";
  if (raw.includes("store_name")) return "读取门店名称、营业时间、地址和联系电话。";
  if (raw.includes("order_hotpot_8821")) return "读取火锅双人餐订单状态与退款/改约能力。";
  return raw.length > 120 ? `${raw.slice(0, 120)}...` : raw;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-slate-50 p-2 text-center">
      <div className="text-sm font-bold">{value}</div>
      <div className="mt-1 text-[10px] text-slate-500">{label}</div>
    </div>
  );
}

function ActionButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="rounded-2xl bg-slate-100 py-2 text-xs font-semibold">
      {label}
    </button>
  );
}

function InfoCard({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div className="rounded-[22px] bg-white p-4 shadow-sm">
      <div className="mb-3 text-sm font-bold">{title}</div>
      <div className="space-y-2">
        {rows.map(([key, value]) => (
          <div key={key} className="flex gap-3 text-sm">
            <span className="w-16 shrink-0 text-slate-400">{key}</span>
            <span className="font-medium text-slate-800">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function actorLabel(actor: string) {
  const map: Record<string, string> = { user: "用户", agent: "智能体", tool: "系统工具", system: "系统" };
  return map[actor] ?? actor;
}

function formatActionResult(actionId: string, title: string, result: Record<string, unknown>) {
  if (actionId === "regenerate_qr" && result.new_code) {
    return `已${title}。新券码 ${result.new_code}，请让商家重新扫码。`;
  }
  if (actionId === "contact_merchant" && result.message_sent) {
    return `已${title}，预计 ${result.eta_minutes ?? 5} 分钟内门店会协助处理。`;
  }
  if (actionId === "manual_code" && result.voucher) {
    const voucher = result.voucher as Record<string, unknown>;
    return `请向商家展示券码 ${voucher.code} 进行手动核销。`;
  }
  if (result.ticket_id) return `已${title}，工单 ${result.ticket_id}，客服将优先处理。`;
  if (result.refund_id) return `已提交退款，售后单 ${result.refund_id}。`;
  return `${title}已完成。`;
}

function buildDefaultCards(context: ServiceContext | null): ServiceCard[] {
  if (!context) return [];
  return [
    ...context.orders.slice(0, 1).map((order) => ({
      type: "order" as const,
      title: text(order.title),
      status: text(order.status),
      payload: order,
    })),
    ...context.vouchers.slice(0, 1).map((voucher) => ({
      type: "voucher" as const,
      title: text(voucher.title),
      status: text(voucher.status),
      payload: voucher,
    })),
  ];
}

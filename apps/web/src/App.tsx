import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { buildEdgeContext, createRefund, createSession, executeWorkflowAction, fetchHealth, fetchOperationLogs, fetchServiceContext, streamChat } from "./api/client";
import { ActionSheet } from "./components/ActionSheet";
import { BottomSheet } from "./components/BottomSheet";
import { FulfillmentContextCard } from "./components/FulfillmentContextCard";
import { PhoneShell } from "./components/PhoneShell";
import { PlusMenu, type PlusMenuTarget } from "./components/PlusMenu";
import { PrivacySettings } from "./components/PrivacySettings";
import { ThinkingProcess } from "./components/ThinkingProcess";
import { buildThinkingLines, summarizeWorkflow } from "./lib/thinking";
import type { Message, PipelineStep, PrivacySettings as Settings, ServiceCard, ServiceContext, ToolCall, WorkflowDiagnosis, WorkflowSolution } from "./types";

type SheetPage = "order" | "orders" | "fulfillment" | "settings" | "actions" | null;

const DEFAULT_SETTINGS: Settings = {
  order_access: true,
  voucher_access: true,
  coupon_access: true,
  location_access: true,
  behavior_summary: true,
  stream_response: true,
};

const QUICK_PROMPTS = ["查看券码", "到店核销失败，扫不出来", "联系商家", "我要退款"];

const SHEET_TITLES: Record<Exclude<SheetPage, null>, string> = {
  order: "订单详情",
  orders: "历史订单",
  fulfillment: "服务进度",
  settings: "授权设置",
  actions: "操作记录",
};

const journeyDetail = [
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
  const [sheet, setSheet] = useState<SheetPage>(null);
  const [plusOpen, setPlusOpen] = useState(false);
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
      content: "我会陪你完成这次火锅套餐履约。到店后如果核销有问题，直接跟我说就行。",
    },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamPhase, setStreamPhase] = useState<"idle" | "observing" | "replying">("idle");
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

  const openSheet = useCallback((page: SheetPage) => {
    setPlusOpen(false);
    setSheet(page);
  }, []);

  const send = useCallback(
    async (raw: string) => {
      const content = raw.trim();
      if (!content || streaming) return;
      setInput("");
      setError(null);
      setPlusOpen(false);

      let sid = sessionId;
      if (!sid) {
        const session = await createSession(edge);
        sid = session.session_id;
        setSessionId(sid);
      }

      setMessages((items) => [...items, { id: uid(), role: "user", content }]);
      setStreaming(true);
      setStreamPhase("observing");
      setPipeline([]);
      setWorkflow(null);

      const assistantId = uid();
      let reply = "";
      let latestWorkflow: WorkflowDiagnosis | null = null;
      try {
        await streamChat(sid, content, edge, {
          onPipeline: (payload) => {
            setStreamPhase("replying");
            const steps = payload.pipeline.steps ?? [];
            setPipeline(steps);
            setServiceCards((payload.service_cards ?? []) as ServiceCard[]);
            if (payload.case) {
              latestWorkflow = payload.case as WorkflowDiagnosis;
              setWorkflow(latestWorkflow);
            }
          },
          onToken: (token) => {
            setStreamPhase("replying");
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
            if (data.workflow || data.case) {
              latestWorkflow = (data.workflow ?? data.case) as WorkflowDiagnosis;
              setWorkflow(latestWorkflow);
            }
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
          },
          onError: (err) => {
            setError(err.message);
          },
        });
      } finally {
        setStreaming(false);
        setStreamPhase("idle");
      }
    },
    [edge, sessionId, streaming]
  );

  const hotpotOrder = context?.orders.find((order) => text(order.id) === "order_hotpot_8821") ?? context?.orders[0];
  const hotpotVoucher = context?.vouchers.find((voucher) => text(voucher.id) === "voucher_hotpot_8821") ?? context?.vouchers[0];

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
        { id: uid(), role: "assistant", content: formatActionResult(actionId, title, result) },
      ]);
      fetchOperationLogs("user_demo", sessionId).then((res) => setOperationLogs(res.logs ?? [])).catch(() => undefined);
      refreshContext();
    } catch {
      setError(`执行「${title}」失败，请稍后重试`);
    }
  };

  const thinkingLines = buildThinkingLines(pipeline, workflow, streaming);
  const thinkingSummary = streaming ? null : summarizeWorkflow(workflow);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0f0f10] px-3 py-4 text-slate-950">
      <PhoneShell>
        <header className="shrink-0 bg-[#111] px-4 pb-2.5 pt-1 text-white">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[10px] text-white/45">抖音生活服务</div>
              <div className="text-base font-bold">AI履约服务管家</div>
            </div>
            <div className="text-right">
              <div className="text-[10px] text-white/40">在线 · {llmMode}</div>
              <button type="button" onClick={() => openSheet("settings")} className="mt-1 text-[11px] text-white/70">
                设置
              </button>
            </div>
          </div>
        </header>

        <ConversationView
          context={context}
          order={hotpotOrder}
          voucher={hotpotVoucher}
          messages={messages}
          streaming={streaming}
          streamPhase={streamPhase}
          input={input}
          error={error}
          workflow={workflow}
          thinkingLines={thinkingLines}
          thinkingSummary={thinkingSummary}
          plusOpen={plusOpen}
          verificationCodeVersion={verificationCodeVersion}
          onInput={setInput}
          onSend={send}
          onOpenSheet={openSheet}
          onTogglePlus={() => setPlusOpen((v) => !v)}
          onClosePlus={() => setPlusOpen(false)}
          onRefund={setRefundOrderId}
          onWorkflowAction={runWorkflowAction}
        />

        <BottomSheet title={sheet ? SHEET_TITLES[sheet] : ""} open={sheet !== null} onClose={() => setSheet(null)}>
          <DetailContent
            page={sheet ?? "order"}
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
            onSelectOrder={(orderId) => {
              void orderId;
              setSheet("order");
            }}
          />
        </BottomSheet>

        {refundOrderId && (
          <ActionSheet
            title="确认申请退款"
            description="系统会基于订单状态、券核销情况和商家规则创建售后单。"
            primaryText="提交退款"
            onPrimary={submitRefund}
            onClose={() => setRefundOrderId(null)}
          />
        )}
      </PhoneShell>
    </div>
  );
}

function ConversationView({
  context,
  order,
  voucher,
  messages,
  streaming,
  streamPhase,
  input,
  error,
  workflow,
  thinkingLines,
  thinkingSummary,
  plusOpen,
  verificationCodeVersion,
  onInput,
  onSend,
  onOpenSheet,
  onTogglePlus,
  onClosePlus,
  onRefund,
  onWorkflowAction,
}: {
  context: ServiceContext | null;
  order?: Record<string, unknown>;
  voucher?: Record<string, unknown>;
  messages: Message[];
  streaming: boolean;
  streamPhase: "idle" | "observing" | "replying";
  input: string;
  error: string | null;
  workflow: WorkflowDiagnosis | null;
  thinkingLines: ReturnType<typeof buildThinkingLines>;
  thinkingSummary: string | null;
  plusOpen: boolean;
  verificationCodeVersion: number;
  onInput: (value: string) => void;
  onSend: (value: string) => void;
  onOpenSheet: (page: SheetPage) => void;
  onTogglePlus: () => void;
  onClosePlus: () => void;
  onRefund: (orderId: string) => void;
  onWorkflowAction: (actionId: string, title: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const solutions = workflow?.solution ?? [];
  const streamingAssistant =
    streaming && messages.length > 0 && messages[messages.length - 1].role === "assistant"
      ? messages[messages.length - 1]
      : null;
  const settledMessages = streamingAssistant ? messages.slice(0, -1) : messages;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, streaming, thinkingLines.length, workflow]);

  return (
    <>
      <main ref={scrollRef} className="flex-1 overflow-y-auto bg-[#f5f5f5] px-3 py-3">
        <div className="flex min-h-full flex-col gap-2.5">
          <FulfillmentContextCard
            orderTitle={text(order?.title, undefined)}
            userName={text(context?.user.display_name, undefined)}
            city={text(context?.user.city, undefined)}
            paidAmount={text(order?.paid_amount, "168")}
            voucherCode={text(voucher?.code, undefined)}
            statusLabel={text(voucher?.status, "待核销") === "unused" ? "待核销" : text(voucher?.status, "待核销")}
            onOpenProgress={() => onOpenSheet("fulfillment")}
            onOpenOrder={() => onOpenSheet("order")}
          />

          {settledMessages.map((message) => (
            <div key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[88%] rounded-2xl px-3 py-2 text-sm leading-relaxed ${
                  message.role === "user" ? "bg-[#111] text-white" : "bg-white text-slate-900 shadow-sm"
                }`}
              >
                {message.content}
              </div>
            </div>
          ))}

          {streaming && (
            <ThinkingProcess lines={thinkingLines} active summary={null} />
          )}

          {streamingAssistant && (
            <div className="flex justify-start">
              <div className="max-w-[88%] rounded-2xl bg-white px-3 py-2 text-sm leading-relaxed text-slate-900 shadow-sm">
                {streamingAssistant.content || "…"}
              </div>
            </div>
          )}

          {!streaming && thinkingLines.length > 0 && (
            <ThinkingProcess lines={thinkingLines} active={false} summary={thinkingSummary} />
          )}

          {!streaming && solutions.length > 0 && (
            <SolutionChips solutions={solutions} onSend={onSend} onWorkflowAction={onWorkflowAction} />
          )}

          {error && <div className="rounded-xl bg-red-50 px-3 py-2 text-xs text-red-600">{error}</div>}

          <div className="mt-auto pt-1">
            <div className="flex gap-2 overflow-x-auto pb-1">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => onSend(prompt)}
                  disabled={streaming}
                  className="shrink-0 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 disabled:opacity-50"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        </div>
      </main>

      <footer className="relative shrink-0 border-t border-slate-100 bg-white px-3 py-2.5">
        <PlusMenu open={plusOpen} onClose={onClosePlus} onSelect={onOpenSheet} />
        <div className="flex items-end gap-2">
          <input
            className="min-h-[42px] flex-1 rounded-full bg-slate-100 px-4 py-2.5 text-sm outline-none"
            placeholder="描述您的履约问题，例如扫不出来、想退款…"
            value={input}
            onChange={(event) => onInput(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && onSend(input)}
            disabled={streaming}
          />
          <button
            type="button"
            onClick={onTogglePlus}
            disabled={streaming}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white text-lg text-slate-600 disabled:opacity-50"
            aria-label="更多服务"
          >
            +
          </button>
          <button
            type="button"
            onClick={() => onSend(input)}
            disabled={streaming || !input.trim()}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#fe2c55] text-white disabled:opacity-40"
            aria-label="发送"
          >
            ↑
          </button>
        </div>
        <div className="mt-1.5 text-center text-[10px] text-slate-400">核销码 v{verificationCodeVersion}</div>
      </footer>
    </>
  );
}

function SolutionChips({
  solutions,
  onSend,
  onWorkflowAction,
}: {
  solutions: WorkflowSolution[];
  onSend: (value: string) => void;
  onWorkflowAction: (actionId: string, title: string) => void;
}) {
  return (
    <div className="rounded-2xl bg-white p-2.5 shadow-sm">
      <div className="mb-2 text-xs font-semibold text-slate-700">您可以这样继续</div>
      <div className="flex flex-wrap gap-2">
        {solutions.slice(0, 4).map((item) => (
          <button
            key={item.action_id}
            type="button"
            onClick={() =>
              item.action_id === "human_handoff" ? onSend("帮我转人工") : onWorkflowAction(item.action_id, item.title)
            }
            className="rounded-full bg-[#fff1f3] px-3 py-1.5 text-xs font-semibold text-[#fe2c55]"
          >
            {item.title}
          </button>
        ))}
      </div>
    </div>
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
  onSelectOrder,
}: {
  page: Exclude<SheetPage, null>;
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
  onSelectOrder: (orderId: string) => void;
}) {
  if (page === "settings") {
    return <PrivacySettings settings={settings} onToggle={onToggle} />;
  }

  return (
    <div className="space-y-3 pb-4">
      {page === "orders" && (
        <div className="space-y-2">
          {(context?.orders ?? []).map((item) => (
            <button
              key={String(item.id)}
              type="button"
              onClick={() => onSelectOrder(String(item.id))}
              className="w-full rounded-2xl bg-white p-3 text-left shadow-sm"
            >
              <div className="text-sm font-bold">{text(item.title)}</div>
              <div className="mt-1 flex items-center justify-between text-xs text-slate-500">
                <span>{text(item.status)}</span>
                <span>¥{text(item.paid_amount)}</span>
              </div>
            </button>
          ))}
        </div>
      )}

      {page === "order" && (
        <div className="space-y-3">
          <InfoCard
            title="订单信息"
            rows={[
              ["商品", text(order?.title)],
              ["状态", text(order?.status)],
              ["实付", `¥${text(order?.paid_amount)}`],
              ["是否可退", order?.can_refund ? "支持退款" : "暂不支持"],
            ]}
          />
          <InfoCard
            title="团购券"
            rows={[
              ["券码", text(voucher?.code)],
              ["状态", text(voucher?.status)],
              ["有效期", text(voucher?.valid_to)],
              ["规则", text(voucher?.usage_rule)],
            ]}
          />
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
          {journeyDetail.map(([name, desc], index) => (
            <div key={name} className="rounded-2xl bg-white p-3">
              <div className="flex items-center gap-3">
                <span
                  className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${
                    index <= 4 ? "bg-[#fe2c55] text-white" : "bg-slate-100"
                  }`}
                >
                  {index + 1}
                </span>
                <div>
                  <div className="text-sm font-bold">{name}</div>
                  <div className="text-xs text-slate-500">{desc}</div>
                </div>
              </div>
            </div>
          ))}
          <button
            type="button"
            onClick={() => onSend("到店核销失败，扫不出来")}
            className="w-full rounded-2xl bg-[#111] py-3 text-sm font-semibold text-white"
          >
            让 AI 帮我处理核销问题
          </button>
          <button
            type="button"
            onClick={() => onWorkflowAction("regenerate_qr", "重新生成核销码")}
            className="w-full rounded-2xl bg-[#fe2c55] py-3 text-sm font-semibold text-white"
          >
            重新生成核销码
          </button>
        </div>
      )}

      {page === "actions" && (
        <>
          <OperationRecords pipeline={pipeline} toolCalls={toolCalls} operationLogs={operationLogs} />
          <InfoCard
            title="用户上下文"
            rows={[
              ["用户", text(context?.user.display_name)],
              ["城市", text(context?.user.city)],
              ["订单数", String(context?.orders.length ?? 0)],
              ["券包数", String((context?.vouchers.length ?? 0) + (context?.coupons.length ?? 0))],
            ]}
          />
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
    detail: humanizeLogDetail(log),
    tone: String(log.actor ?? "agent"),
  }));
  const records = [
    ...persisted.slice(0, 8),
    ...pipeline.map((step) => ({
      actor: "管家",
      title: stepName(step.name),
      detail: humanizeStepDetail(step),
      tone: "agent",
    })),
    ...toolCalls.map((call) => ({
      actor: "系统",
      title: toolName(call.name),
      detail: toolSummary(call.result),
      tone: "tool",
    })),
  ];

  return (
    <div className="rounded-[22px] bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-bold">操作记录</div>
          <div className="mt-1 text-xs text-slate-500">本次履约服务中的关键动作</div>
        </div>
        <span className="rounded-full bg-[#fff1f3] px-2 py-1 text-[10px] font-semibold text-[#fe2c55]">{records.length} 条</span>
      </div>
      <div className="mt-4 space-y-3">
        {records.map((record, index) => (
          <div key={`${record.actor}-${record.title}-${index}`} className="flex gap-3">
            <div className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${dotClass(record.tone)}`} />
            <div className="flex-1 border-b border-slate-100 pb-3 last:border-b-0">
              <div className="text-[11px] font-semibold text-slate-400">{record.actor}</div>
              <div className="mt-1 text-sm font-bold">{record.title}</div>
              <div className="mt-1 text-xs leading-relaxed text-slate-500">{record.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function humanizeLogDetail(log: Record<string, unknown>) {
  const summary = String(log.summary ?? "");
  if (summary.includes("Case")) {
    return summary.replace(/Case\s+[A-Z]+-\d+/g, "问题").slice(0, 80);
  }
  return summary.slice(0, 80) || "已记录";
}

function humanizeStepDetail(step: PipelineStep) {
  const detail = step.detail ?? "已完成";
  return detail
    .replace(/\b(IC|PC|FC|AC|CC)-\d{3}\b/g, "")
    .replace(/P[0-3]/g, "")
    .replace(/\s{2,}/g, " ")
    .trim() || "已完成";
}

function dotClass(tone: string) {
  if (tone === "user") return "bg-[#111]";
  if (tone === "tool") return "bg-[#fe2c55]";
  return "bg-emerald-500";
}

function stepName(name: string) {
  const names: Record<string, string> = {
    intent_detect: "理解您的需求",
    workflow_match: "匹配处理方式",
    service_context: "查看订单与券",
    knowledge_search: "查阅服务说明",
    diagnosis_tree: "核对问题原因",
    case_generate: "整理解决方案",
    tool_action: "调取业务信息",
    prompt_build: "组织回复",
    model_response: "生成回复",
  };
  return names[name] ?? name;
}

function toolName(name: string) {
  const names: Record<string, string> = {
    query_order: "查询订单",
    query_voucher: "查询团购券",
    query_coupon: "查询优惠券",
    query_store: "查询门店",
    query_refund: "查询售后",
    create_refund_case: "创建退款申请",
    create_service_ticket: "创建服务工单",
    transfer_to_human: "转人工",
    run_diagnosis: "完成问题核对",
  };
  return names[name] ?? name;
}

function toolSummary(result: unknown) {
  if (!result) return "已完成";
  if (typeof result === "object" && result !== null && "case_name" in result) {
    return `确认问题：${String((result as Record<string, unknown>).case_name)}`;
  }
  const raw = JSON.stringify(result);
  if (raw.includes("store_name")) return "已读取门店名称、营业时间和联系方式";
  if (raw.includes("vouchers")) return "已读取团购券状态和券码";
  if (raw.includes("order")) return "已读取订单状态与退款能力";
  return "相关信息已就绪";
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
  const map: Record<string, string> = { user: "您", agent: "管家", tool: "系统", system: "系统" };
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
    const v = result.voucher as Record<string, unknown>;
    return `请向商家展示券码 ${v.code} 进行手动核销。`;
  }
  if (result.ticket_id) return `已${title}，工单 ${result.ticket_id}，客服将优先处理。`;
  if (result.refund_id) return `已提交退款，售后单 ${result.refund_id}。`;
  return `${title}已完成。`;
}

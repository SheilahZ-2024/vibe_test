import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { buildEdgeContext, createRefund, createSession, executeWorkflowAction, fetchFulfillmentTimeline, fetchHealth, fetchServiceContext, fetchServiceRecords, fetchUserSample, fetchWelcome, streamChat } from "./api/client";
import { ServiceProgressPanel, ServiceRecordsPanel, type ServiceRecord, type TimelineStage } from "./components/ServicePanels";
import { ActionSheet } from "./components/ActionSheet";
import { BottomSheet } from "./components/BottomSheet";
import { DemoUserSwitcher, SAMPLE_SIZE } from "./components/DemoUserSwitcher";
import { OrderFocusPanel } from "./components/OrderFocusPanel";
import { PhoneShell } from "./components/PhoneShell";
import { PlusMenu, type PlusMenuTarget } from "./components/PlusMenu";
import { PrivacySettings } from "./components/PrivacySettings";
import { ThinkingStream } from "./components/ThinkingStream";
import { THINKING_PLACEHOLDER, appendThinkingLine } from "./lib/thinking";
import { reservationLabel } from "./lib/reservation";
import { getStoredFocusOrderId, resolveFocusOrderId, setStoredFocusOrderId } from "./lib/orderFocus";
import { getStoredUserId, resolveUserId, setStoredUserId } from "./lib/userSession";
import type { Message, PendingWriteAction, PrivacySettings as Settings, ServiceCard, ServiceContext, UserListItem, WorkflowDiagnosis, WorkflowSolution } from "./types";

type SheetPage = "order" | "orders" | "fulfillment" | "settings" | "actions" | null;

const DEFAULT_SETTINGS: Settings = {
  order_access: true,
  voucher_access: true,
  coupon_access: true,
  location_access: true,
  behavior_summary: true,
  stream_response: true,
};

const QUICK_PROMPTS = ["查看券码", "核销遇到问题", "联系商家", "我要退款"];

const SHEET_TITLES: Record<Exclude<SheetPage, null>, string> = {
  order: "订单详情",
  orders: "历史订单",
  fulfillment: "服务进度",
  settings: "授权设置",
  actions: "操作记录",
};

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

function text(value: unknown, fallback = "-") {
  return value == null ? fallback : String(value);
}

export default function App() {
  const [sheet, setSheet] = useState<SheetPage>(null);
  const [plusOpen, setPlusOpen] = useState(false);
  const [userList, setUserList] = useState<UserListItem[]>([]);
  const [userTotal, setUserTotal] = useState(0);
  const [reshufflingUsers, setReshufflingUsers] = useState(false);
  const [userId, setUserId] = useState(() => getStoredUserId());
  const [booting, setBooting] = useState(true);
  const [welcomeLoading, setWelcomeLoading] = useState(false);
  const [settings, setSettings] = useState<Settings>(() => {
    const saved = localStorage.getItem("douyin-life-settings");
    return saved ? JSON.parse(saved) : DEFAULT_SETTINGS;
  });
  const [context, setContext] = useState<ServiceContext | null>(null);
  const [focusOrderId, setFocusOrderId] = useState<string | null>(() => getStoredFocusOrderId(getStoredUserId()));
  const edge = useMemo(
    () => buildEdgeContext(settings, userId, context, focusOrderId),
    [settings, userId, context, focusOrderId],
  );
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamPhase, setStreamPhase] = useState<"idle" | "observing" | "replying">("idle");
  const [thinkingText, setThinkingText] = useState("");
  const [workflow, setWorkflow] = useState<WorkflowDiagnosis | null>(null);
  const [serviceRecords, setServiceRecords] = useState<ServiceRecord[]>([]);
  const [timelineStages, setTimelineStages] = useState<TimelineStage[]>([]);
  const [sheetLoading, setSheetLoading] = useState(false);
  const [serviceCards, setServiceCards] = useState<ServiceCard[]>([]);
  const [refundOrderId, setRefundOrderId] = useState<string | null>(null);
  const [writeConfirm, setWriteConfirm] = useState<PendingWriteAction | null>(null);
  const [verificationCodeVersion, setVerificationCodeVersion] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [llmMode, setLlmMode] = useState("—");
  const thinkingPlaceholderRef = useRef(false);

  useEffect(() => {
    localStorage.setItem("douyin-life-settings", JSON.stringify(settings));
  }, [settings]);

  useEffect(() => {
    if (!context) return;
    const orderIds = context.orders.map((order) => String(order.id));
    const resolved = resolveFocusOrderId(getStoredFocusOrderId(userId), orderIds);
    setFocusOrderId(resolved);
    if (resolved !== getStoredFocusOrderId(userId)) setStoredFocusOrderId(resolved, userId);
  }, [context, userId]);

  const handleFocusOrder = useCallback(
    (orderId: string) => {
      setStoredFocusOrderId(orderId, userId);
      setFocusOrderId(orderId);
    },
    [userId],
  );

  const syncFocusFromServer = useCallback(
    (orderId: string | null | undefined) => {
      if (!orderId) return;
      const orderIds = context?.orders.map((o) => String(o.id)) ?? [];
      if (!orderIds.includes(orderId)) return;
      setStoredFocusOrderId(orderId, userId);
      setFocusOrderId(orderId);
    },
    [context, userId],
  );

  const loadUserSample = useCallback(async (includeUserId?: string) => {
    const sample = await fetchUserSample(SAMPLE_SIZE, includeUserId);
    setUserTotal(sample.total);
    setUserList(sample.users);
    return sample;
  }, []);

  const loadServiceRecords = useCallback(async (uid: string = userId) => {
    try {
      const res = await fetchServiceRecords(uid);
      setServiceRecords(res.records ?? []);
    } catch {
      setServiceRecords([]);
    }
  }, [userId]);

  const loadTimeline = useCallback(
    async (orderId?: string | null, uid: string = userId) => {
      const oid = orderId ?? focusOrderId ?? (context?.orders[0]?.id ? String(context.orders[0].id) : null);
      if (!oid) {
        setTimelineStages([]);
        return;
      }
      try {
        const res = await fetchFulfillmentTimeline(uid, oid);
        setTimelineStages(res.stages ?? []);
      } catch {
        setTimelineStages([]);
      }
    },
    [userId, focusOrderId, context],
  );

  const bootstrapUser = useCallback(async (nextUserId: string) => {
    setError(null);
    setWelcomeLoading(true);
    const ctx = await fetchServiceContext(nextUserId);
    setContext(ctx);
    const welcomeRes = await fetchWelcome(nextUserId);
    const nextEdge = buildEdgeContext(settings, nextUserId, ctx, getStoredFocusOrderId(nextUserId));
    const session = await createSession(nextEdge);
    setSessionId(session.session_id);
    setMessages([{ id: uid(), role: "assistant", content: welcomeRes.welcome }]);
    setWorkflow(null);
    setServiceRecords([]);
    setTimelineStages([]);
    setServiceCards([]);
    setRefundOrderId(null);
    setVerificationCodeVersion(1);
    setWelcomeLoading(false);
    void loadServiceRecords(nextUserId);
    return ctx;
  }, [settings, loadServiceRecords]);

  useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        fetchHealth().then((h) => setLlmMode(h.llm_mode)).catch(() => setLlmMode("offline"));
        const stored = getStoredUserId();
        const sample = await loadUserSample(stored);
        if (cancelled) return;
        const resolved = resolveUserId(
          stored,
          sample.users.map((item) => item.id)
        );
        if (resolved !== stored) {
          await loadUserSample(resolved);
        }
        setUserId(resolved);
        setStoredUserId(resolved);
        await bootstrapUser(resolved);
      } catch {
        if (!cancelled) setError("初始化失败，请检查后端服务");
      } finally {
        if (!cancelled) setBooting(false);
      }
    }
    void init();
    return () => {
      cancelled = true;
    };
    // 仅首次挂载拉取用户列表
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reshuffleUsers = useCallback(async () => {
    if (reshufflingUsers || streaming || welcomeLoading) return;
    setReshufflingUsers(true);
    try {
      await loadUserSample(userId);
    } catch {
      setError("换一批用户失败");
    } finally {
      setReshufflingUsers(false);
    }
  }, [loadUserSample, reshufflingUsers, streaming, userId, welcomeLoading]);

  const refreshContext = useCallback(() => {
    fetchServiceContext(userId).then(setContext).catch(() => setError("刷新上下文失败"));
  }, [userId]);

  const switchUser = useCallback(async (nextUserId: string) => {
    if (nextUserId === userId || streaming || welcomeLoading) return;
    setStoredUserId(nextUserId);
    setUserId(nextUserId);
    setSheet(null);
    setPlusOpen(false);
    try {
      await bootstrapUser(nextUserId);
    } catch {
      setError("切换用户失败");
    }
  }, [bootstrapUser, streaming, userId, welcomeLoading]);

  const openSheet = useCallback(
    (page: SheetPage) => {
      setPlusOpen(false);
      setSheet(page);
      if (page === "actions") {
        setSheetLoading(true);
        void loadServiceRecords().finally(() => setSheetLoading(false));
      }
      if (page === "fulfillment") {
        setSheetLoading(true);
        void loadTimeline().finally(() => setSheetLoading(false));
      }
    },
    [loadServiceRecords, loadTimeline],
  );

  useEffect(() => {
    if (sheet !== "fulfillment") return;
    setSheetLoading(true);
    void loadTimeline().finally(() => setSheetLoading(false));
  }, [focusOrderId, sheet, loadTimeline]);

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
      thinkingPlaceholderRef.current = true;
      setThinkingText(THINKING_PLACEHOLDER);
      setWorkflow(null);

      const assistantId = uid();
      let reply = "";
      let latestWorkflow: WorkflowDiagnosis | null = null;
      try {
        await streamChat(sid, content, edge, {
          onPipeline: (payload) => {
            const steps = payload.pipeline?.steps ?? [];
            if (steps.some((s) => s.name === "agent_gather" || s.name === "agent_gather_react" || s.name === "agent_compose" || s.name === "agent_decision")) {
              setStreamPhase("observing");
            }
            setServiceCards((payload.service_cards ?? []) as ServiceCard[]);
            syncFocusFromServer(payload.focus_order_id as string | undefined);
            if (payload.case) {
              latestWorkflow = payload.case as WorkflowDiagnosis;
              setWorkflow(latestWorkflow);
            }
          },
          onThinking: (payload) => {
            if (payload.line) {
              setThinkingText((prev) => {
                if (thinkingPlaceholderRef.current) {
                  thinkingPlaceholderRef.current = false;
                  return payload.line!.trim();
                }
                return appendThinkingLine(prev, payload.line!);
              });
            }
            setStreamPhase("observing");
          },
          onThinkingToken: (token) => {
            setThinkingText((prev) => {
              if (thinkingPlaceholderRef.current) {
                thinkingPlaceholderRef.current = false;
                return token;
              }
              return prev + token;
            });
            setStreamPhase("observing");
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
            setStreamPhase("idle");
            thinkingPlaceholderRef.current = false;
            setThinkingText("");
            setServiceCards((data.service_cards ?? []) as ServiceCard[]);
            syncFocusFromServer(data.focus_order_id as string | undefined);
            if (data.workflow || data.case) {
              latestWorkflow = (data.workflow ?? data.case) as WorkflowDiagnosis;
              setWorkflow(latestWorkflow);
            } else {
              setWorkflow(null);
            }
            const pending = (data.pending_confirmations ?? []) as PendingWriteAction[];
            if (pending.length > 0 && !latestWorkflow?.solution?.length) {
              setWriteConfirm(pending[0]);
            }
            void loadServiceRecords();
            if (sheet === "fulfillment") void loadTimeline();
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
                  tool_calls: (data.tool_calls ?? []) as Message["tool_calls"],
                },
              ];
            });
          },
          onError: (err) => {
            thinkingPlaceholderRef.current = false;
            setThinkingText("");
            setError(err.message);
          },
        });
      } finally {
        thinkingPlaceholderRef.current = false;
        setStreaming(false);
        setStreamPhase("idle");
      }
    },
    [edge, sessionId, streaming, userId, syncFocusFromServer, loadServiceRecords, loadTimeline, sheet],
  );

  const primaryOrder = useMemo(() => {
    if (!context?.orders.length) return undefined;
    if (focusOrderId) {
      return context.orders.find((order) => String(order.id) === focusOrderId);
    }
    if (context.orders.length === 1) return context.orders[0];
    return undefined;
  }, [context, focusOrderId]);
  const primaryVoucher =
    context?.vouchers.find((voucher) => voucher.order_id === primaryOrder?.id) ?? context?.vouchers[0];
  const primaryStore = useMemo(() => {
    const storeId = primaryOrder?.store_id ?? primaryVoucher?.store_id;
    return context?.stores.find((store) => store.id === storeId) ?? context?.stores[0];
  }, [context, primaryOrder, primaryVoucher]);

  const submitRefund = async () => {
    if (!refundOrderId || !sessionId) return;
    const orderId = refundOrderId;
    const result = await createRefund(sessionId, orderId, "用户在履约服务管家中发起退款", userId);
    setRefundOrderId(null);
    setMessages((items) => [
      ...items,
      { id: uid(), role: "assistant", content: `退款申请已提交，售后单 ${result.id}，我会继续跟进处理进度。` },
    ]);
    refreshContext();
    void loadServiceRecords();
    void loadTimeline(orderId);
  };

  const confirmWriteAction = async () => {
    if (!writeConfirm || !sessionId) return;
    const item = writeConfirm;
    setWriteConfirm(null);
    if (item.action_id === "apply_refund" && item.order_id) {
      const result = await createRefund(sessionId, item.order_id, String(item.payload?.reason ?? "用户确认退款"), userId);
      setMessages((items) => [
        ...items,
        { id: uid(), role: "assistant", content: `好的，退款申请已提交，售后单 ${result.id}。` },
      ]);
    } else {
      await runWorkflowAction(
        item.action_id,
        item.title,
        item.order_id ?? undefined,
        item.voucher_id ?? undefined,
      );
    }
    refreshContext();
    void loadServiceRecords();
    void loadTimeline();
  };

  const runWorkflowAction = async (
    actionId: string,
    title: string,
    orderIdOverride?: string,
    voucherIdOverride?: string,
  ) => {
    if (!sessionId) return;
    const orderId = orderIdOverride ?? (primaryOrder?.id ? String(primaryOrder.id) : undefined);
    const voucherId = voucherIdOverride ?? (primaryVoucher?.id ? String(primaryVoucher.id) : undefined);
    try {
      const result = await executeWorkflowAction(
        sessionId,
        actionId,
        orderId,
        voucherId,
        undefined,
        userId
      );
      if (actionId === "regenerate_qr") setVerificationCodeVersion((value) => value + 1);
      setMessages((items) => [
        ...items,
        { id: uid(), role: "assistant", content: formatActionResult(actionId, title, result) },
      ]);
      refreshContext();
      void loadServiceRecords();
      void loadTimeline();
    } catch {
      setError(`执行「${title}」失败，请稍后重试`);
    }
  };

  const showThinking = streaming && thinkingText.trim().length > 0;
  const thinkingCompact = streamPhase === "replying";

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-200 px-3 py-4 text-slate-950">
      <PhoneShell>
        <header className="shrink-0 border-b border-slate-100 bg-white px-4 pb-3 pt-1">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[10px] font-medium text-[#fe2c55]">抖音生活服务</div>
              <div className="text-base font-bold text-slate-900">AI 履约服务管家</div>
            </div>
            <div className="text-right">
              <div className="text-[10px] text-slate-400">在线 · {llmMode}</div>
              <button
                type="button"
                onClick={() => openSheet("settings")}
                className="mt-1 text-[11px] font-medium text-slate-600 hover:text-[#fe2c55]"
              >
                设置
              </button>
            </div>
          </div>
          <DemoUserSwitcher
            users={userList}
            totalUsers={userTotal}
            value={userId}
            onChange={switchUser}
            onReshuffle={reshuffleUsers}
            disabled={streaming || booting || welcomeLoading}
            reshuffling={reshufflingUsers}
          />
        </header>

        {booting || welcomeLoading ? (
          <div className="flex flex-1 items-center justify-center bg-[#f5f5f5] px-4 text-sm text-slate-500">
            {booting ? "正在加载用户列表…" : "正在生成欢迎语…"}
          </div>
        ) : (
        <ConversationView
          context={context}
          messages={messages}
          streaming={streaming}
          input={input}
          error={error}
          workflow={workflow}
          thinkingNarrative={thinkingText}
          showThinking={showThinking}
          thinkingCompact={thinkingCompact}
          plusOpen={plusOpen}
          verificationCodeVersion={verificationCodeVersion}
          onInput={setInput}
          onSend={send}
          onOpenSheet={openSheet}
          onTogglePlus={() => setPlusOpen((v) => !v)}
          onClosePlus={() => setPlusOpen(false)}
          onRefund={setRefundOrderId}
          onWorkflowAction={runWorkflowAction}
          focusOrderId={focusOrderId}
          onFocusOrder={handleFocusOrder}
        />
        )}

        <BottomSheet title={sheet ? SHEET_TITLES[sheet] : ""} open={sheet !== null} onClose={() => setSheet(null)}>
          <DetailContent
            page={sheet ?? "order"}
            context={context}
            order={primaryOrder}
            voucher={primaryVoucher}
            store={primaryStore}
            settings={settings}
            serviceRecords={serviceRecords}
            timelineStages={timelineStages}
            sheetLoading={sheetLoading}
            onToggle={(key) => setSettings((current) => ({ ...current, [key]: !current[key] }))}
            onSend={send}
            onRefund={setRefundOrderId}
            onWorkflowAction={runWorkflowAction}
            onSelectOrder={(orderId) => {
              handleFocusOrder(orderId);
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

        {writeConfirm && (
          <ActionSheet
            title={`确认${writeConfirm.title}`}
            description={writeConfirm.description || "此操作将修改您的订单或发起服务请求，请确认。"}
            primaryText="确认执行"
            onPrimary={() => void confirmWriteAction()}
            onClose={() => setWriteConfirm(null)}
          />
        )}
      </PhoneShell>
    </div>
  );
}

function ConversationView({
  context,
  messages,
  streaming,
  input,
  error,
  workflow,
  thinkingNarrative,
  showThinking,
  thinkingCompact,
  plusOpen,
  verificationCodeVersion,
  onInput,
  onSend,
  onOpenSheet,
  onTogglePlus,
  onClosePlus,
  onRefund,
  onWorkflowAction,
  focusOrderId,
  onFocusOrder,
}: {
  context: ServiceContext | null;
  messages: Message[];
  streaming: boolean;
  input: string;
  error: string | null;
  workflow: WorkflowDiagnosis | null;
  thinkingNarrative: string;
  showThinking: boolean;
  thinkingCompact: boolean;
  plusOpen: boolean;
  verificationCodeVersion: number;
  onInput: (value: string) => void;
  onSend: (value: string) => void;
  onOpenSheet: (page: SheetPage) => void;
  onTogglePlus: () => void;
  onClosePlus: () => void;
  onRefund: (orderId: string) => void;
  onWorkflowAction: (actionId: string, title: string) => void;
  focusOrderId: string | null;
  onFocusOrder: (orderId: string) => void;
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
  }, [messages, streaming, thinkingNarrative, workflow]);

  return (
    <>
      <main ref={scrollRef} className="flex-1 overflow-y-auto bg-[#f5f5f5] px-3 py-3">
        <div className="flex min-h-full flex-col gap-2.5">
          <OrderFocusPanel
            orders={context?.orders ?? []}
            vouchers={context?.vouchers ?? []}
            focusOrderId={focusOrderId}
            onFocusOrder={onFocusOrder}
            onOpenOrders={() => onOpenSheet("orders")}
            onOpenProgress={() => onOpenSheet("fulfillment")}
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

          {showThinking && (
            <ThinkingStream text={thinkingNarrative} active={streaming && !thinkingCompact} compact={thinkingCompact} />
          )}

          {streamingAssistant && streamingAssistant.content ? (
            <div className="flex justify-start">
              <div className="max-w-[88%] rounded-2xl bg-white px-3 py-2 text-sm leading-relaxed text-slate-900 shadow-sm">
                {streamingAssistant.content}
              </div>
            </div>
          ) : null}

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
  store,
  settings,
  serviceRecords,
  timelineStages,
  sheetLoading,
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
  store?: Record<string, unknown>;
  settings: Settings;
  serviceRecords: ServiceRecord[];
  timelineStages: TimelineStage[];
  sheetLoading: boolean;
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
              ["预约", reservationLabel(voucher?.usage_rule) || "—"],
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
        <ServiceProgressPanel
          stages={timelineStages}
          loading={sheetLoading}
          orderTitle={order?.title ? String(order.title) : undefined}
          onAskAi={() => onSend("核销遇到问题，帮我处理一下")}
          onRegenerateQr={() => onWorkflowAction("regenerate_qr", "重新生成核销码")}
        />
      )}

      {page === "actions" && (
        <ServiceRecordsPanel records={serviceRecords} loading={sheetLoading} />
      )}
    </div>
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

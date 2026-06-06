import type { EdgeContext, PipelineStep, PrivacySettings, ServiceContext, UserListItem } from "../types";
import { getStoredUserId } from "../lib/userSession";
import { getStoredFocusOrderId } from "../lib/orderFocus";

// 生产环境走同源 /api 代理；本地 dev 由 Vite proxy 转发
const API = import.meta.env.VITE_API_BASE_URL ?? "";

export function buildEdgeContext(
  settings: PrivacySettings,
  userId?: string,
  ctx?: ServiceContext | null,
  focusOrderId?: string | null,
): EdgeContext {
  const uid = userId ?? getStoredUserId();
  const city = settings.location_access ? String(ctx?.user.city ?? "北京") : "未知";
  const recentOrderIds = settings.order_access
    ? (ctx?.orders ?? []).slice(0, 3).map((order) => String(order.id))
    : [];
  const voucherSummary = settings.voucher_access
    ? (ctx?.vouchers ?? []).slice(0, 3).map((voucher) => `${voucher.title} · ${voucher.status}`)
    : [];
  const behaviorTags = settings.behavior_summary ? ["近期频繁查看团购券", "关注退款进度"] : [];
  const focus =
    focusOrderId !== undefined ? focusOrderId : getStoredFocusOrderId(uid);
  const payload = {
    user_id: uid,
    focus_order_id: focus,
    city,
    recent_order_ids: recentOrderIds,
    local_voucher_summary: voucherSummary,
    behavior_tags: behaviorTags,
    location_permission: settings.location_access,
  };
  return { ...payload, packet_size_bytes: new Blob([JSON.stringify(payload)]).size };
}

export async function createSession(edge: EdgeContext): Promise<{ session_id: string; user_id: string }> {
  const res = await fetch(`${API}/api/v1/chat/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(edge),
    cache: "no-store",
  });
  if (!res.ok) throw new Error("创建会话失败");
  return res.json();
}

/** 从 DB 全量用户中随机抽取样本（默认 10 人） */
export async function fetchUserSample(count = 10, includeUserId?: string): Promise<{
  total: number;
  sample_size: number;
  users: UserListItem[];
}> {
  const params = new URLSearchParams({ count: String(count) });
  if (includeUserId) params.set("include_user_id", includeUserId);
  const res = await fetch(`${API}/api/v1/users/sample?${params}`);
  if (!res.ok) throw new Error("读取用户样本失败");
  return res.json();
}

export async function fetchUsers(limit = 500, offset = 0): Promise<UserListItem[]> {
  const res = await fetch(`${API}/api/v1/users?limit=${limit}&offset=${offset}`);
  if (!res.ok) throw new Error("读取用户列表失败");
  return res.json();
}

export async function fetchUserCount(): Promise<number> {
  const res = await fetch(`${API}/api/v1/meta/users/count`);
  if (!res.ok) throw new Error("读取用户总数失败");
  const data = (await res.json()) as { total?: number };
  return Number(data.total ?? 0);
}

/** 分页拉取 DB 全量用户（后端单页最多 500） */
export async function fetchAllUsers(): Promise<UserListItem[]> {
  const total = await fetchUserCount();
  if (total <= 0) return fetchUsers(500, 0);
  const pageSize = 500;
  const items: UserListItem[] = [];
  for (let offset = 0; offset < total; offset += pageSize) {
    const batch = await fetchUsers(Math.min(pageSize, total - offset), offset);
    items.push(...batch);
    if (batch.length < pageSize) break;
  }
  return items;
}

export async function fetchWelcome(userId: string): Promise<{ welcome: string; source: string }> {
  const res = await fetch(`${API}/api/v1/chat/welcome`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId }),
    cache: "no-store",
  });
  if (!res.ok) throw new Error("生成欢迎语失败");
  return res.json();
}

export async function fetchServiceContext(userId?: string): Promise<ServiceContext> {
  const uid = userId ?? getStoredUserId();
  const res = await fetch(`${API}/api/v1/users/${uid}/service-context`);
  if (!res.ok) throw new Error("读取生活服务上下文失败");
  return res.json();
}

/** 统一换行符，避免 SSE `\r\n` 导致帧切分/JSON 解析失败。 */
function normalizeSseText(text: string): string {
  return text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

function splitSseFrames(buffer: string): { frames: string[]; rest: string } {
  const normalized = normalizeSseText(buffer);
  const parts = normalized.split("\n\n");
  const rest = parts.pop() ?? "";
  return { frames: parts, rest };
}

function parseSseFrame(frame: string): { event: string; data: string } | null {
  if (!frame.trim()) return null;
  let event = "message";
  const dataLines: string[] = [];
  for (const rawLine of normalizeSseText(frame).split("\n")) {
    const line = rawLine.trim();
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      const value = line.slice(5);
      dataLines.push(value.startsWith(" ") ? value.slice(1) : value);
    }
  }
  const data = dataLines.join("\n").trim();
  return data ? { event, data } : null;
}

function parseSseJson(data: string): unknown {
  return JSON.parse(data.replace(/\r/g, ""));
}

type StreamChatHandlers = {
  onPipeline?: (payload: {
    intent?: string;
    pipeline?: { steps?: PipelineStep[] };
    service_cards?: unknown[];
    case?: Record<string, unknown>;
    focus_order_id?: string | null;
    agent_trace?: Array<Record<string, unknown>>;
  }) => void;
  onThinking?: (payload: { line?: string }) => void;
  onThinkingToken?: (text: string) => void;
  onToken?: (text: string) => void;
  onDone?: (data: Record<string, unknown>) => void;
  onError?: (err: Error) => void;
};

function dispatchSseEvent(
  event: string,
  parsed: Record<string, unknown>,
  handlers: StreamChatHandlers,
  state: { sawDone: boolean },
): void {
  if (event === "pipeline") {
    handlers.onPipeline?.(parsed as Parameters<NonNullable<StreamChatHandlers["onPipeline"]>>[0]);
  }
  if (event === "thinking" && parsed.line) handlers.onThinking?.({ line: String(parsed.line) });
  if (event === "thinking_token" && parsed.text) handlers.onThinkingToken?.(String(parsed.text));
  if (event === "token" && parsed.text) handlers.onToken?.(String(parsed.text));
  if (event === "error") {
    throw new Error(String(parsed.message ?? "服务端处理失败"));
  }
  if (event === "done") {
    state.sawDone = true;
    handlers.onDone?.(parsed);
  }
}

function consumeSseFrame(frame: string, handlers: StreamChatHandlers, state: { sawDone: boolean }): void {
  const parsedFrame = parseSseFrame(frame);
  if (!parsedFrame) return;
  const { event, data } = parsedFrame;
  let parsed: unknown;
  try {
    parsed = parseSseJson(data);
  } catch {
    console.warn("[streamChat] 跳过无法解析的 SSE 帧", { event, preview: data.slice(0, 120) });
    return;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return;
  dispatchSseEvent(event, parsed as Record<string, unknown>, handlers, state);
}

export async function streamChat(
  sessionId: string,
  message: string,
  edge: EdgeContext,
  handlers: StreamChatHandlers,
  timeoutMs = 120_000
): Promise<void> {
  const state = { sawDone: false };
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${API}/api/v1/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ session_id: sessionId, message, edge_context: edge, stream: true }),
      signal: controller.signal,
      cache: "no-store",
    });
    if (!res.ok || !res.body) {
      handlers.onError?.(new Error(`对话请求失败：${res.status}`));
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const split = splitSseFrames(buffer);
      buffer = split.rest;
      for (const frame of split.frames) {
        try {
          consumeSseFrame(frame, handlers, state);
        } catch (err) {
          handlers.onError?.(err instanceof Error ? err : new Error("服务端处理失败"));
          return;
        }
      }
    }

    buffer += decoder.decode();
    if (buffer.trim()) {
      const split = splitSseFrames(`${buffer}\n\n`);
      for (const frame of split.frames) {
        try {
          consumeSseFrame(frame, handlers, state);
        } catch (err) {
          handlers.onError?.(err instanceof Error ? err : new Error("服务端处理失败"));
          return;
        }
      }
    }

    if (!state.sawDone) {
      handlers.onError?.(new Error("对话流提前结束，未收到完整回复"));
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      handlers.onError?.(new Error("模型响应超时，请稍后重试"));
      return;
    }
    handlers.onError?.(err instanceof Error ? err : new Error("对话请求异常"));
  } finally {
    window.clearTimeout(timer);
  }
}

export async function createRefund(sessionId: string, orderId: string, reason: string, userId?: string) {
  const res = await fetch(`${API}/api/v1/refunds`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      order_id: orderId,
      reason,
      user_id: userId ?? getStoredUserId(),
    }),
  });
  if (!res.ok) throw new Error("退款申请失败");
  return res.json();
}

export async function fetchHealth(): Promise<{ status: string; llm_mode: string; llm_ok?: boolean }> {
  const res = await fetch(`${API}/health`);
  if (!res.ok) throw new Error("健康检查失败");
  return res.json();
}

export async function executeWorkflowAction(
  sessionId: string,
  actionId: string,
  orderId?: string,
  voucherId?: string,
  payload?: Record<string, unknown>,
  userId?: string
) {
  const res = await fetch(`${API}/api/v1/workflow/actions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      action_id: actionId,
      order_id: orderId,
      voucher_id: voucherId,
      payload: payload ?? {},
      user_id: userId ?? getStoredUserId(),
    }),
  });
  if (!res.ok) throw new Error("工作流动作执行失败");
  return res.json();
}

export async function fetchFulfillmentTimeline(userId: string, orderId: string) {
  const res = await fetch(`${API}/api/v1/users/${userId}/orders/${orderId}/fulfillment-timeline`);
  if (!res.ok) throw new Error("读取服务进度失败");
  return res.json() as Promise<{ stages?: import("../components/ServicePanels").TimelineStage[]; order_title?: string }>;
}

export async function fetchServiceRecords(userId?: string) {
  const uid = userId ?? getStoredUserId();
  const res = await fetch(`${API}/api/v1/users/${uid}/service-records`);
  if (!res.ok) throw new Error("读取服务记录失败");
  return res.json() as Promise<{ count?: number; records?: import("../components/ServicePanels").ServiceRecord[] }>;
}

export async function fetchOperationLogs(userId?: string, sessionId?: string) {
  const uid = userId ?? getStoredUserId();
  const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  const res = await fetch(`${API}/api/v1/users/${uid}/operation-logs${query}`);
  if (!res.ok) throw new Error("读取操作记录失败");
  return res.json();
}

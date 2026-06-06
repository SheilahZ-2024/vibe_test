import type { EdgeContext, PipelineStep, PrivacySettings, ServiceContext } from "../types";

// 生产环境走同源 /api 代理；本地 dev 由 Vite proxy 转发
const API = import.meta.env.VITE_API_BASE_URL ?? "";

export function buildEdgeContext(settings: PrivacySettings): EdgeContext {
  const recentOrderIds = settings.order_access ? ["order_hotpot_8821", "order_movie_7718"] : [];
  const voucherSummary = settings.voucher_access ? ["川巷子火锅双人餐券未使用", "电影票今晚 20:10"] : [];
  const behaviorTags = settings.behavior_summary ? ["近期频繁查看团购券", "关注退款进度"] : [];
  const payload = {
    user_id: "user_demo",
    city: settings.location_access ? "北京" : "未知",
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

export async function fetchServiceContext(userId = "user_demo"): Promise<ServiceContext> {
  const res = await fetch(`${API}/api/v1/users/${userId}/service-context`);
  if (!res.ok) throw new Error("读取生活服务上下文失败");
  return res.json();
}

function parseSseFrame(frame: string): { event: string; data: string } | null {
  if (!frame.trim()) return null;
  let event = "message";
  let data = "";
  for (const rawLine of frame.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  return data ? { event, data } : null;
}

export async function streamChat(
  sessionId: string,
  message: string,
  edge: EdgeContext,
  handlers: {
    onPipeline?: (payload: {
      intent: string;
      pipeline: { steps?: PipelineStep[] };
      service_cards?: unknown[];
      case?: Record<string, unknown>;
    }) => void;
    onToken?: (text: string) => void;
    onDone?: (data: Record<string, unknown>) => void;
    onError?: (err: Error) => void;
  },
  timeoutMs = 120_000
): Promise<void> {
  let sawDone = false;
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
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const parsedFrame = parseSseFrame(frame);
        if (!parsedFrame) continue;
        const { event, data } = parsedFrame;
        try {
          const parsed = JSON.parse(data);
          if (event === "pipeline") handlers.onPipeline?.(parsed);
          if (event === "token" && parsed.text) handlers.onToken?.(parsed.text);
          if (event === "error") {
            handlers.onError?.(new Error(String(parsed.message ?? "服务端处理失败")));
            return;
          }
          if (event === "done") {
            sawDone = true;
            handlers.onDone?.(parsed);
          }
        } catch {
          handlers.onError?.(new Error("流式响应解析失败"));
          return;
        }
      }
    }

    if (buffer.trim()) {
      const parsedFrame = parseSseFrame(buffer);
      if (parsedFrame) {
        const { event, data } = parsedFrame;
        try {
          const parsed = JSON.parse(data);
          if (event === "pipeline") handlers.onPipeline?.(parsed);
          if (event === "token" && parsed.text) handlers.onToken?.(parsed.text);
          if (event === "error") {
            handlers.onError?.(new Error(String(parsed.message ?? "服务端处理失败")));
            return;
          }
          if (event === "done") {
            sawDone = true;
            handlers.onDone?.(parsed);
          }
        } catch {
          handlers.onError?.(new Error("流式响应解析失败"));
          return;
        }
      }
    }

    if (!sawDone) {
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

export async function createRefund(sessionId: string, orderId: string, reason: string) {
  const res = await fetch(`${API}/api/v1/refunds`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, order_id: orderId, reason }),
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
  payload?: Record<string, unknown>
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
    }),
  });
  if (!res.ok) throw new Error("工作流动作执行失败");
  return res.json();
}

export async function fetchOperationLogs(userId = "user_demo", sessionId?: string) {
  const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  const res = await fetch(`${API}/api/v1/users/${userId}/operation-logs${query}`);
  if (!res.ok) throw new Error("读取操作记录失败");
  return res.json();
}

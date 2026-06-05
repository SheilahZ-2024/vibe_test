import type { EdgeContext, PipelineStep, PrivacySettings, ServiceContext } from "../types";

const API = import.meta.env.VITE_API_BASE_URL || "";

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
  });
  if (!res.ok) throw new Error("创建会话失败");
  return res.json();
}

export async function fetchServiceContext(userId = "user_demo"): Promise<ServiceContext> {
  const res = await fetch(`${API}/api/v1/users/${userId}/service-context`);
  if (!res.ok) throw new Error("读取生活服务上下文失败");
  return res.json();
}

export async function streamChat(
  sessionId: string,
  message: string,
  edge: EdgeContext,
  handlers: {
    onPipeline?: (payload: { intent: string; pipeline: { steps?: PipelineStep[] }; service_cards?: unknown[] }) => void;
    onToken?: (text: string) => void;
    onDone?: (data: Record<string, unknown>) => void;
    onError?: (err: Error) => void;
  }
): Promise<void> {
  const res = await fetch(`${API}/api/v1/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ session_id: sessionId, message, edge_context: edge, stream: true }),
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
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        if (line.startsWith("data: ")) data = line.slice(6);
      }
      if (!data) continue;
      try {
        const parsed = JSON.parse(data);
        if (event === "pipeline") handlers.onPipeline?.(parsed);
        if (event === "token" && parsed.text) handlers.onToken?.(parsed.text);
        if (event === "done") handlers.onDone?.(parsed);
      } catch {
        // Ignore malformed SSE frames.
      }
    }
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

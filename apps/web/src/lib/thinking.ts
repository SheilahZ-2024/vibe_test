/** 用户可见思考叙述 — 由服务端 thinking 事件逐段推送 */

const INTENT_ZH: Record<string, string> = {
  VoucherUnavailable: "团购券核销或用不了",
  MerchantReject: "商家拒绝核销",
  RefundRequest: "申请退款",
  QueryVoucher: "查看团购券",
  QueryOrder: "查看订单",
  QueryStore: "查看门店",
  QueryRefund: "了解退款",
  QueryCoupon: "优惠券问题",
  HumanTransfer: "转人工",
  clarify: "需求尚不明确",
  chitchat: "寒暄",
};

/** 兜底清洗：去掉英文意图名、匹配意图等内部表述 */
export function sanitizeThinkingLine(line: string): string {
  let out = line.trim();
  if (!out) return out;

  for (const [code, zh] of Object.entries(INTENT_ZH)) {
    out = out.replaceAll(code, zh);
  }

  out = out.replace(/\b[A-Z][a-zA-Z]{2,}(?:Request|Failure|Reject|Unavailable|Transfer|Complaint|Dispute|Eligibility)\b/g, "");
  out = out.replace(/匹配.*?意图/g, "理解您的需求");
  out = out.replace(/我判断这属于【[^】]+】（[^）]+）/g, "");
  out = out.replace(/\b(configured|unconfigured|keyword|semantic|intent)\b/gi, "");
  out = out.replace(/\s{2,}/g, " ").trim();

  return out;
}

export function appendThinkingLine(lines: string[], line: string): string[] {
  const trimmed = sanitizeThinkingLine(line);
  if (!trimmed) return lines;
  if (lines.includes(trimmed)) return lines;
  return [...lines, trimmed];
}

/** 多行展示 */
export function formatThinkingDisplay(lines: string[], streaming = false): string {
  if (lines.length === 0) {
    return streaming ? "我听您说一下情况…" : "";
  }
  return lines.filter(Boolean).join("\n");
}

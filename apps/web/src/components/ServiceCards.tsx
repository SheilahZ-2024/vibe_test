import type { ServiceCard, ServiceContext } from "../types";

const statusText: Record<string, string> = {
  unused: "未使用",
  scheduled: "已预约",
  refund_pending: "退款中",
  refunding: "退款中",
  processing: "处理中",
  available: "可用",
  unavailable: "不可用",
};

export function ContextOverview({ context }: { context: ServiceContext | null }) {
  if (!context) {
    return <div className="rounded-2xl bg-white border border-slate-100 p-3 text-xs text-slate-500">正在读取生活服务上下文...</div>;
  }
  const user = context.user;
  return (
    <div className="rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-white p-4">
      <div className="text-sm font-semibold">你好，{String(user.display_name ?? "用户")}</div>
      <div className="text-xs opacity-90 mt-1">
        {String(user.city ?? "北京")} · {String(user.membership_level ?? "生活服务用户")}
      </div>
      <div className="grid grid-cols-3 gap-2 mt-4 text-center">
        <Metric label="订单" value={context.orders.length} />
        <Metric label="券包" value={context.vouchers.length + context.coupons.length} />
        <Metric label="售后" value={context.refunds.length} />
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl bg-white/15 py-2">
      <div className="text-lg font-bold">{value}</div>
      <div className="text-[10px] opacity-80">{label}</div>
    </div>
  );
}

export function ServiceCards({
  cards,
  context,
  onRefund,
}: {
  cards: ServiceCard[];
  context: ServiceContext | null;
  onRefund: (orderId: string) => void;
}) {
  const fallback = context
    ? [
        ...context.orders.slice(0, 2).map((o) => ({
          type: "order" as const,
          title: String(o.title),
          status: String(o.status),
          payload: o,
        })),
        ...context.vouchers.slice(0, 1).map((v) => ({
          type: "voucher" as const,
          title: String(v.title),
          status: String(v.status),
          payload: v,
        })),
        ...context.coupons.slice(0, 1).map((c) => ({
          type: "coupon" as const,
          title: String(c.title),
          status: String(c.status),
          payload: c,
        })),
      ]
    : [];
  const display = cards.length ? cards : fallback;

  return (
    <div className="space-y-2">
      {display.map((card, idx) => (
        <div key={`${card.type}-${idx}`} className="rounded-2xl bg-white border border-slate-100 p-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[10px] text-indigo-600 font-semibold">{labelFor(card.type)}</div>
              <div className="text-sm font-semibold mt-1">{card.title}</div>
              <div className="text-xs text-slate-500 mt-1">{subtitle(card)}</div>
            </div>
            <span className="text-[10px] rounded-full bg-slate-100 px-2 py-1 text-slate-600 shrink-0">
              {statusText[card.status] ?? card.status}
            </span>
          </div>
          {card.type === "order" && card.payload.can_refund === true && (
            <button
              type="button"
              onClick={() => onRefund(String(card.payload.id))}
              className="mt-3 text-xs px-3 py-1.5 rounded-full bg-orange-50 text-orange-600"
            >
              申请退款
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

function labelFor(type: ServiceCard["type"]) {
  return { order: "生活服务订单", voucher: "团购券", coupon: "优惠券", refund: "售后进度" }[type];
}

function text(value: unknown, fallback = "-") {
  return value == null ? fallback : String(value);
}

function subtitle(card: ServiceCard) {
  const p = card.payload;
  if (card.type === "order") return `实付 ${text(p.paid_amount)} 元 · ${text(p.service_type, "")}`;
  if (card.type === "voucher") return `券码 ${text(p.code)} · ${text(p.usage_rule, "")}`;
  if (card.type === "coupon") return text(p.rule_text, "");
  if (card.type === "refund") return text(p.reason, "");
  return "";
}

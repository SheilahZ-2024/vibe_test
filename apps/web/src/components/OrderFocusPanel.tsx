function text(value: unknown, fallback = "—") {
  return value == null ? fallback : String(value);
}

function statusLabel(status: unknown) {
  const s = String(status ?? "");
  if (s === "unused") return "待核销";
  if (s === "scheduled") return "已预约";
  if (s === "refunding") return "退款中";
  if (s === "used") return "已使用";
  return s || "—";
}

export function OrderFocusPanel({
  orders,
  vouchers,
  focusOrderId,
  onFocusOrder,
  onOpenOrders,
  onOpenProgress,
}: {
  orders: Record<string, unknown>[];
  vouchers: Record<string, unknown>[];
  focusOrderId: string | null;
  onFocusOrder: (orderId: string) => void;
  onOpenOrders: () => void;
  onOpenProgress: () => void;
}) {
  const focused = orders.find((o) => String(o.id) === focusOrderId);

  return (
    <div className="rounded-2xl border border-slate-100 bg-white p-3 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-[10px] font-semibold text-[#fe2c55]">我的订单 · 点选聚焦</div>
          <div className="text-[11px] text-slate-500">AI 将围绕你选中的订单处理（共 {orders.length} 笔）</div>
        </div>
        <button type="button" onClick={onOpenOrders} className="text-[10px] font-medium text-slate-500 hover:text-[#fe2c55]">
          全部
        </button>
      </div>

      <ul className="mt-2 max-h-40 space-y-1.5 overflow-y-auto">
        {orders.length === 0 ? (
          <li className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-400">暂无订单</li>
        ) : (
          orders.map((order) => {
            const id = String(order.id);
            const selected = id === focusOrderId;
            const voucher = vouchers.find((v) => String(v.order_id) === id);
            return (
              <li key={id}>
                <button
                  type="button"
                  onClick={() => onFocusOrder(id)}
                  className={`flex w-full items-start gap-2 rounded-xl border px-2.5 py-2 text-left transition ${
                    selected
                      ? "border-[#fe2c55]/40 bg-[#fff1f3]"
                      : "border-slate-100 bg-slate-50 hover:border-slate-200 hover:bg-white"
                  }`}
                >
                  <span
                    className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                      selected ? "border-[#fe2c55] bg-[#fe2c55]" : "border-slate-300 bg-white"
                    }`}
                  >
                    {selected ? <span className="h-1.5 w-1.5 rounded-full bg-white" /> : null}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={`block truncate text-sm ${selected ? "font-semibold text-[#fe2c55]" : "font-medium text-slate-800"}`}>
                      {text(order.title)}
                    </span>
                    <span className="block truncate text-[10px] text-slate-500">
                      {statusLabel(order.status)} · ¥{text(order.paid_amount)}
                      {voucher?.code ? ` · 券 ${String(voucher.code)}` : ""}
                    </span>
                  </span>
                </button>
              </li>
            );
          })
        )}
      </ul>

      {focused && (
        <button
          type="button"
          onClick={onOpenProgress}
          className="mt-2 w-full rounded-xl bg-slate-900 py-2 text-xs font-semibold text-white"
        >
          查看「{text(focused.title, "订单")}」履约进度
        </button>
      )}

      {!focusOrderId && orders.length > 1 && (
        <p className="mt-2 text-[10px] text-amber-600">请先点选一笔订单，或在对话中说明要处理哪一单</p>
      )}
    </div>
  );
}

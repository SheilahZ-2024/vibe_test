const journey = [
  ["发现", "已选套餐"],
  ["购买", "已支付"],
  ["预约", "可预约"],
  ["到店", "待到店"],
  ["核销", "待处理"],
  ["消费", "—"],
  ["售后", "—"],
];

function text(value: unknown, fallback = "—") {
  return value == null ? fallback : String(value);
}

export function FulfillmentContextCard({
  orderTitle,
  userName,
  city,
  paidAmount,
  voucherCode,
  statusLabel = "待核销",
  onOpenProgress,
  onOpenOrder,
}: {
  orderTitle?: string;
  userName?: string;
  city?: string;
  paidAmount?: string;
  voucherCode?: string;
  statusLabel?: string;
  onOpenProgress: () => void;
  onOpenOrder: () => void;
}) {
  return (
    <div className="rounded-2xl border border-slate-100 bg-gradient-to-br from-white to-slate-50 p-3 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <button type="button" onClick={onOpenOrder} className="min-w-0 flex-1 text-left">
          <div className="text-[10px] font-semibold text-[#fe2c55]">当前履约</div>
          <div className="mt-0.5 truncate text-sm font-bold text-slate-900">{text(orderTitle, "川巷子火锅双人餐")}</div>
          <div className="mt-0.5 text-[10px] text-slate-500">
            {text(userName, "小林")} · {text(city, "北京")} · 实付 ¥{text(paidAmount, "168")}
            {voucherCode ? ` · 券码 ${voucherCode}` : ""}
          </div>
        </button>
        <span className="shrink-0 rounded-full bg-[#fff1f3] px-2 py-0.5 text-[10px] font-semibold text-[#fe2c55]">
          {statusLabel}
        </span>
      </div>
      <button type="button" onClick={onOpenProgress} className="mt-2.5 w-full text-left">
        <div className="flex gap-1 overflow-x-auto pb-0.5">
          {journey.map(([title, desc], index) => (
            <div
              key={title}
              className={`min-w-[52px] shrink-0 rounded-xl px-1.5 py-1 text-center ${
                index < 4
                  ? "bg-emerald-50 text-emerald-700"
                  : index === 4
                    ? "bg-[#fff1f3] text-[#fe2c55]"
                    : "bg-slate-100 text-slate-400"
              }`}
            >
              <div className="text-[9px] font-bold">{title}</div>
              <div className="mt-0.5 truncate text-[8px] opacity-80">{desc}</div>
            </div>
          ))}
        </div>
      </button>
    </div>
  );
}

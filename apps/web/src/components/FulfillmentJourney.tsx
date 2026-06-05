const steps = [
  { key: "discover", title: "发现团购", desc: "火锅双人餐 ¥168" },
  { key: "purchase", title: "购买订单", desc: "订单已支付" },
  { key: "reserve", title: "预约", desc: "建议提前 2 小时" },
  { key: "arrive", title: "到店", desc: "望京店 10:30-22:30" },
  { key: "verify", title: "核销", desc: "Demo 主冲突点" },
  { key: "consume", title: "消费", desc: "问题解决后完成" },
  { key: "afterSales", title: "售后", desc: "退款/投诉/人工" },
];

export function FulfillmentJourney({
  active,
  onStep,
}: {
  active: string;
  onStep: (step: string) => void;
}) {
  const activeIndex = Math.max(0, steps.findIndex((step) => step.key === active));
  return (
    <div className="rounded-2xl bg-white border border-slate-100 p-3">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-sm font-bold">火锅套餐履约旅程</div>
          <div className="text-[11px] text-slate-500">AI 嵌入旅程，不是独立聊天机器人</div>
        </div>
        <span className="text-[10px] rounded-full bg-indigo-50 text-indigo-600 px-2 py-1">P0 Demo</span>
      </div>
      <div className="space-y-2">
        {steps.map((step, index) => {
          const done = index < activeIndex;
          const current = index === activeIndex;
          return (
            <button
              key={step.key}
              type="button"
              onClick={() => onStep(step.key)}
              className={`w-full text-left flex gap-3 p-2 rounded-xl border transition ${
                current
                  ? "border-indigo-200 bg-indigo-50"
                  : done
                    ? "border-emerald-100 bg-emerald-50/50"
                    : "border-slate-100 bg-slate-50"
              }`}
            >
              <span
                className={`w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold shrink-0 ${
                  current ? "bg-indigo-600 text-white" : done ? "bg-emerald-500 text-white" : "bg-white text-slate-400"
                }`}
              >
                {done ? "✓" : index + 1}
              </span>
              <span>
                <span className="block text-xs font-semibold">{step.title}</span>
                <span className="block text-[11px] text-slate-500 mt-0.5">{step.desc}</span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

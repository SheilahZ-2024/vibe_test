const labels: Record<string, string> = {
  query_order: "查询订单",
  query_voucher: "查询团购券",
  query_coupon: "查询优惠券",
  query_store: "查询门店",
  query_refund: "查询售后规则",
  create_refund_case: "创建退款申请",
  create_service_ticket: "创建服务工单",
  transfer_to_human: "转人工",
  diagnose_voucher_issue: "自动诊断核销失败",
};

export function ToolCallPanel({ calls }: { calls: { name: string; result?: unknown }[] }) {
  if (!calls.length) {
    return (
      <div className="rounded-2xl bg-white border border-slate-100 p-3 text-xs text-slate-500">
        触发服务办理后，这里会展示 AI 调用了哪些业务工具。
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-white border border-slate-100 p-3">
      <div className="text-xs font-bold mb-2">AI 做了什么</div>
      <div className="space-y-2">
        {calls.map((call, index) => (
          <div key={`${call.name}-${index}`} className="rounded-xl bg-slate-50 border border-slate-100 p-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-indigo-600">{labels[call.name] ?? call.name}</span>
              <span className="text-[10px] text-emerald-600">done</span>
            </div>
            <div className="text-[10px] text-slate-500 mt-1 line-clamp-2">{summary(call.result)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function summary(value: unknown) {
  if (!value) return "无返回";
  const text = JSON.stringify(value);
  return text.length > 180 ? `${text.slice(0, 180)}...` : text;
}

import { formatDateTime } from "../lib/format";

export interface TimelineStage {
  key: string;
  title: string;
  state: string;
  label: string;
  occurred_at: string | null;
  detail?: string | null;
  extra?: Record<string, unknown>;
}

export interface ServiceRecord {
  id: string;
  kind: "refund" | "operation";
  title: string;
  summary: string;
  status?: string;
  status_label?: string;
  money_amount?: number | null;
  money_status?: string | null;
  order_id?: string | null;
  order_title?: string | null;
  actor?: string;
  occurred_at?: string | null;
  estimated_finish_time?: string | null;
  operation_type?: string;
}

export function ServiceProgressPanel({
  stages,
  loading,
  orderTitle,
  onAskAi,
  onRegenerateQr,
}: {
  stages: TimelineStage[];
  loading?: boolean;
  orderTitle?: string;
  onAskAi: () => void;
  onRegenerateQr: () => void;
}) {
  if (loading) {
    return <div className="rounded-2xl bg-white p-4 text-sm text-slate-500">加载履约进度…</div>;
  }

  if (!stages.length) {
    return (
      <div className="rounded-2xl bg-white p-4 text-sm text-slate-500">
        请先选择一笔订单查看服务进度
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {orderTitle ? (
        <div className="rounded-2xl bg-white px-3 py-2 text-xs text-slate-500">
          当前订单：<span className="font-semibold text-slate-800">{orderTitle}</span>
        </div>
      ) : null}
      <p className="px-1 text-[11px] leading-relaxed text-slate-400">
        团购履约以「核销」视为套餐已使用，不再单独展示「消费」节点。
      </p>
      {stages.map((stage, index) => (
        <StageRow key={stage.key} stage={stage} index={index} />
      ))}
      <button
        type="button"
        onClick={onAskAi}
        className="w-full rounded-2xl bg-[#111] py-3 text-sm font-semibold text-white"
      >
        让 AI 帮我处理核销问题
      </button>
      <button
        type="button"
        onClick={onRegenerateQr}
        className="w-full rounded-2xl bg-[#fe2c55] py-3 text-sm font-semibold text-white"
      >
        重新生成核销码
      </button>
    </div>
  );
}

function StageRow({ stage, index }: { stage: TimelineStage; index: number }) {
  const done = stage.state === "done" || stage.state === "success" || stage.state === "approved";
  const skipped = stage.state === "skipped";
  const pending = stage.state === "pending" || stage.state === "submitted" || stage.state === "processing";

  return (
    <div className="rounded-2xl bg-white p-3">
      <div className="flex gap-3">
        <span
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
            done ? "bg-emerald-500 text-white" : skipped ? "bg-slate-100 text-slate-400" : pending ? "bg-amber-400 text-white" : "bg-[#fe2c55] text-white"
          }`}
        >
          {done ? "✓" : index + 1}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-bold text-slate-900">{stage.title}</span>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                done ? "bg-emerald-50 text-emerald-700" : skipped ? "bg-slate-100 text-slate-500" : "bg-amber-50 text-amber-700"
              }`}
            >
              {stage.label}
            </span>
          </div>
          {stage.occurred_at ? (
            <div className="mt-1 text-[11px] font-medium text-slate-600">{formatDateTime(stage.occurred_at)}</div>
          ) : (
            <div className="mt-1 text-[11px] text-slate-400">尚未触发</div>
          )}
          {stage.detail ? <div className="mt-1 text-xs leading-relaxed text-slate-500">{stage.detail}</div> : null}
          {stage.extra?.money_status ? (
            <div className="mt-1 text-xs text-amber-700">{String(stage.extra.money_status)}</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function ServiceRecordsPanel({
  records,
  loading,
}: {
  records: ServiceRecord[];
  loading?: boolean;
}) {
  if (loading) {
    return <div className="rounded-2xl bg-white p-4 text-sm text-slate-500">加载操作记录…</div>;
  }

  if (!records.length) {
    return (
      <div className="rounded-2xl bg-white p-4 text-sm text-slate-500">
        暂无服务记录。发起退款、咨询或办理后会出现在这里。
      </div>
    );
  }

  return (
    <div className="rounded-[22px] bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-bold">服务记录</div>
          <div className="mt-1 text-xs text-slate-500">购买、咨询、退款与办理进度</div>
        </div>
        <span className="rounded-full bg-[#fff1f3] px-2 py-1 text-[10px] font-semibold text-[#fe2c55]">
          {records.length} 条
        </span>
      </div>
      <div className="mt-4 space-y-3">
        {records.map((record) => (
          <RecordRow key={record.id} record={record} />
        ))}
      </div>
    </div>
  );
}

function RecordRow({ record }: { record: ServiceRecord }) {
  const isRefund = record.kind === "refund";
  return (
    <div className="flex gap-3 border-b border-slate-100 pb-3 last:border-b-0">
      <div className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${isRefund ? "bg-amber-500" : "bg-emerald-500"}`} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[11px] font-semibold text-slate-400">{record.actor ?? "系统"}</span>
          {record.occurred_at ? (
            <span className="text-[10px] text-slate-400">{formatDateTime(record.occurred_at)}</span>
          ) : null}
        </div>
        <div className="mt-1 text-sm font-bold text-slate-900">{record.title}</div>
        <div className="mt-1 text-xs leading-relaxed text-slate-600">{record.summary}</div>
        {record.order_title ? (
          <div className="mt-1 text-[11px] text-slate-500">关联订单：{record.order_title}</div>
        ) : null}
        {record.money_amount != null ? (
          <div className="mt-1 text-xs font-semibold text-slate-800">金额 ¥{record.money_amount}</div>
        ) : null}
        {record.money_status ? (
          <div className={`mt-1 text-xs ${isRefund ? "text-amber-700" : "text-slate-500"}`}>{record.money_status}</div>
        ) : null}
        {record.status_label && !record.money_status ? (
          <div className="mt-1 text-xs text-slate-500">{record.status_label}</div>
        ) : null}
        {record.estimated_finish_time ? (
          <div className="mt-0.5 text-[10px] text-slate-400">
            预计完成：{formatDateTime(record.estimated_finish_time)}
          </div>
        ) : null}
      </div>
    </div>
  );
}

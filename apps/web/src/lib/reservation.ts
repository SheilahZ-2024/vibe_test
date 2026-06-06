/** 从券 usage_rule 文案推导预约展示标签（与后端 usage_rules 对齐） */
export function reservationLabel(usageRule: unknown, supportsReservation?: unknown): string {
  const rule = String(usageRule ?? "");
  if (/须预约|提前预约|预约成功|未预约不可/.test(rule)) return "须预约";
  if (/无需预约|随到随用|直接到店/.test(rule)) return "无需预约";
  if (supportsReservation === true) return "须预约";
  return "";
}

export function reservationBadgeClass(label: string): string {
  if (label === "须预约") return "bg-amber-50 text-amber-700";
  if (label === "无需预约") return "bg-slate-100 text-slate-600";
  return "bg-slate-100 text-slate-500";
}

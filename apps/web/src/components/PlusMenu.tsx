import { useEffect, useRef } from "react";

const ITEMS = [
  { id: "fulfillment" as const, label: "服务进度", desc: "购买→到店→核销全流程" },
  { id: "orders" as const, label: "历史订单", desc: "查看全部订单与券码" },
  { id: "actions" as const, label: "操作记录", desc: "本次服务的处理记录" },
  { id: "settings" as const, label: "授权设置", desc: "数据与隐私授权" },
];

export type PlusMenuTarget = (typeof ITEMS)[number]["id"];

export function PlusMenu({
  open,
  onClose,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  onSelect: (target: PlusMenuTarget) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      ref={ref}
      className="absolute bottom-full right-0 z-20 mb-2 w-56 overflow-hidden rounded-2xl border border-slate-100 bg-white shadow-xl"
    >
      {ITEMS.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => {
            onSelect(item.id);
            onClose();
          }}
          className="flex w-full flex-col items-start border-b border-slate-50 px-3 py-2.5 text-left last:border-b-0 active:bg-slate-50"
        >
          <span className="text-sm font-semibold text-slate-900">{item.label}</span>
          <span className="mt-0.5 text-[10px] text-slate-500">{item.desc}</span>
        </button>
      ))}
    </div>
  );
}

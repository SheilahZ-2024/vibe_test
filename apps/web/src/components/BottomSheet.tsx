import type { ReactNode } from "react";

export function BottomSheet({
  title,
  open,
  onClose,
  children,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!open) return null;

  return (
    <div className="absolute inset-0 z-30 flex flex-col justify-end">
      <button type="button" aria-label="关闭" className="absolute inset-0 bg-black/45" onClick={onClose} />
      <section className="relative max-h-[78%] rounded-t-[28px] bg-[#f5f5f5] shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-200/80 px-4 py-3">
          <div className="text-base font-bold text-slate-900">{title}</div>
          <button type="button" onClick={onClose} className="rounded-full bg-white px-3 py-1 text-xs text-slate-500">
            关闭
          </button>
        </div>
        <div className="overflow-y-auto px-3 py-3">{children}</div>
      </section>
    </div>
  );
}

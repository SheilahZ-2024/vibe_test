import type { ReactNode } from "react";

export function PhoneShell({ children }: { children: ReactNode }) {
  return (
    <div className="w-[390px] h-[844px] rounded-[44px] border-2 border-slate-300 shadow-2xl overflow-hidden bg-slate-50 flex flex-col relative">
      <div className="h-11 px-6 pt-3 flex justify-between text-sm font-semibold shrink-0">
        <span>9:41</span>
        <span>●●●</span>
      </div>
      {children}
      <div className="h-5 bg-white flex justify-center pt-1.5 shrink-0">
        <span className="w-28 h-1 bg-slate-800 rounded-full opacity-80" />
      </div>
    </div>
  );
}

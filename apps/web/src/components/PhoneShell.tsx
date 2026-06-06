import { useEffect, useState, type ReactNode } from "react";

function formatStatusBarTime(date: Date) {
  return `${date.getHours()}:${date.getMinutes().toString().padStart(2, "0")}`;
}

function useStatusBarTime() {
  const [time, setTime] = useState(() => formatStatusBarTime(new Date()));
  useEffect(() => {
    const tick = () => setTime(formatStatusBarTime(new Date()));
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, []);
  return time;
}

export function PhoneShell({ children }: { children: ReactNode }) {
  const statusTime = useStatusBarTime();

  return (
    <div className="w-[390px] h-[844px] rounded-[44px] border-2 border-slate-300 shadow-2xl overflow-hidden bg-slate-50 flex flex-col relative">
      <div className="h-11 px-6 pt-3 flex justify-between text-sm font-semibold shrink-0">
        <span>{statusTime}</span>
        <span>●●●</span>
      </div>
      {children}
      <div className="h-5 bg-white flex justify-center pt-1.5 shrink-0">
        <span className="w-28 h-1 bg-slate-800 rounded-full opacity-80" />
      </div>
    </div>
  );
}

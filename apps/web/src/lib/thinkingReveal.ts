import { useEffect, useRef, useState } from "react";

/** 标点停顿 — 模拟说话节奏 */
function pauseMs(ch: string, lag: number): number {
  if (ch === "\n") return lag > 60 ? 120 : 240;
  if ("。！？".includes(ch)) return 260;
  if ("…".includes(ch)) return 220;
  if ("，、；".includes(ch)) return 130;
  if ("：:".includes(ch)) return 90;
  if (ch === " ") return 24;
  // 落后太多时略加速，但不整段蹦出
  if (lag > 80) return 22;
  if (lag > 40) return 30;
  return 36 + Math.floor(Math.random() * 14);
}

/**
 * 将后端推来的 thinking 文本逐字揭示，避免「一坨一坨」跳出。
 * active=false 时立即展示全文（流结束/进入正式回复）。
 */
export function useThinkingReveal(target: string, active: boolean): string {
  const [shown, setShown] = useState("");
  const indexRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    clearTimeout(timerRef.current);

    if (!target) {
      indexRef.current = 0;
      setShown("");
      return;
    }

    if (!active) {
      indexRef.current = target.length;
      setShown(target);
      return;
    }

    if (target.length < indexRef.current) {
      indexRef.current = 0;
      setShown("");
    }

    const schedule = () => {
      const i = indexRef.current;
      if (i >= target.length) return;

      const lag = target.length - i;
      const step = lag > 96 ? 2 : 1;
      const next = Math.min(i + step, target.length);
      indexRef.current = next;
      setShown(target.slice(0, next));

      if (next < target.length) {
        const lastChar = target[next - 1] ?? "";
        timerRef.current = setTimeout(schedule, pauseMs(lastChar, lag));
      }
    };

    if (indexRef.current < target.length) {
      timerRef.current = setTimeout(schedule, 40);
    }

    return () => clearTimeout(timerRef.current);
  }, [target, active]);

  return shown;
}

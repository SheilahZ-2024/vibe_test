import { useThinkingReveal } from "../lib/thinkingReveal";

/** 流式思考 — 单段灰字，逐字有节奏，像人在自言自语 */
export function ThinkingStream({
  text,
  active,
  compact,
}: {
  text: string;
  active?: boolean;
  compact?: boolean;
}) {
  const revealed = useThinkingReveal(text, Boolean(active));

  if (!revealed.trim()) return null;

  return (
    <div className="flex justify-start">
      <div
        className={`max-w-[92%] border-l-2 border-slate-200 pl-3 leading-[1.75] tracking-wide text-slate-400 ${
          compact ? "text-[12px]" : "text-[13px]"
        }`}
      >
        <p className={`whitespace-pre-wrap ${active ? "text-slate-500" : ""}`}>
          {revealed}
          {active && indexBehind(text, revealed) ? (
            <span className="ml-0.5 inline-block animate-pulse text-slate-400">▍</span>
          ) : null}
        </p>
      </div>
    </div>
  );
}

function indexBehind(full: string, shown: string): boolean {
  return shown.length < full.length;
}

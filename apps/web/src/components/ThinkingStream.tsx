import { useThinkingReveal } from "../lib/thinkingReveal";

/** 流式思考 — 展示 Gather/Compose 真实推理，按段灰字 */
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

  const paragraphs = revealed.split(/\n\n+/).filter((p) => p.trim());

  return (
    <div className="flex justify-start">
      <div
        className={`max-w-[92%] border-l-2 border-slate-200/80 pl-3 leading-relaxed tracking-normal text-slate-500/90 ${
          compact ? "text-[12px] leading-[1.65]" : "text-[13px] leading-[1.7]"
        }`}
      >
        {paragraphs.map((para, i) => (
          <p
            key={`${i}-${para.slice(0, 24)}`}
            className={`whitespace-pre-wrap ${i > 0 ? "mt-2.5" : ""} ${active && i === paragraphs.length - 1 ? "text-slate-600" : ""}`}
          >
            {para.trim()}
          </p>
        ))}
        {active ? (
          <span className="mt-1 inline-block h-[1em] w-0.5 animate-pulse bg-slate-400/70 align-middle" aria-hidden />
        ) : null}
      </div>
    </div>
  );
}

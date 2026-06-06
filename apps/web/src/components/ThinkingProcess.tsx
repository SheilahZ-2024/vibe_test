import type { ThinkingLine } from "../lib/thinking";

export function ThinkingProcess({
  lines,
  active,
  summary,
}: {
  lines: ThinkingLine[];
  active: boolean;
  summary?: string | null;
}) {
  if (!lines.length && !summary) return null;

  return (
    <div className="flex justify-start">
      <div className="max-w-[92%] rounded-2xl border border-slate-200/80 bg-white px-3 py-2.5 shadow-sm">
        <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-slate-500">
          {active ? (
            <>
              <span className="inline-flex h-1.5 w-1.5 animate-pulse rounded-full bg-[#fe2c55]" />
              正在帮您处理
            </>
          ) : (
            <>已为您核对</>
          )}
        </div>
        <ul className="space-y-1">
          {lines.map((line, index) => (
            <li key={line.id} className="flex gap-2 text-xs leading-relaxed text-slate-600">
              <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-emerald-400" />
              <span className={active && index === lines.length - 1 ? "text-slate-800" : ""}>{line.text}</span>
            </li>
          ))}
        </ul>
        {summary && !active && (
          <div className="mt-2 rounded-xl bg-[#fff7f8] px-2.5 py-1.5 text-xs text-[#fe2c55]">{summary}</div>
        )}
      </div>
    </div>
  );
}

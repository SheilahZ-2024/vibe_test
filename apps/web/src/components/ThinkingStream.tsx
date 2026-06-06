/** 流式思考过程 — 灰色多行，展示推理/查数/判断 */
export function ThinkingStream({ text, active }: { text: string; active?: boolean }) {
  if (!text.trim()) return null;

  const lines = text.split("\n").filter(Boolean);

  return (
    <div className="flex justify-start">
      <div className="max-w-[92%] space-y-2 border-l-2 border-slate-200 pl-3 text-[13px] leading-relaxed text-slate-400">
        {lines.map((line, i) => {
          const isLast = i === lines.length - 1;
          const isStep = /^#\d+\s/.test(line);
          const display = line.replace(/^#\d+\s/, "");
          return (
            <p
              key={`${i}-${line.slice(0, 32)}`}
              className={isLast && active ? "text-slate-500" : undefined}
            >
              {isStep ? (
                <span className="mr-1 inline-block rounded bg-slate-100 px-1 py-0.5 text-[10px] font-medium text-slate-500">
                  {line.match(/^#(\d+)/)?.[1]}
                </span>
              ) : null}
              {display}
              {isLast && active ? (
                <span className="ml-0.5 inline-block animate-pulse text-slate-400">▍</span>
              ) : null}
            </p>
          );
        })}
      </div>
    </div>
  );
}

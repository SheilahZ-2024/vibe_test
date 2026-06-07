/** 发消息后占位 — 真实 Gather/Compose 推理到达后会被替换 */
export const THINKING_PLACEHOLDER = "正在核实…";

/** 追加一条思考行（段间空行） */
export function appendThinkingLine(prev: string, line: string): string {
  const text = line.trim();
  if (!text) return prev;
  if (!prev || prev === THINKING_PLACEHOLDER) return text;
  return `${prev}\n\n${text}`;
}

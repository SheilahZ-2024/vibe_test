import type { PipelineStep } from "../types";

const names: Record<string, string> = {
  intent_detect: "意图识别",
  turn_plan: "Turn 规划",
  service_context: "读取服务上下文",
  knowledge_search: "检索知识库",
  diagnosis_tree: "执行诊断树",
  case_generate: "生成 Case",
  workflow_match: "服务体系匹配",
  tool_action: "业务工具调用",
  agent_gather: "Gather 核实",
  agent_gather_react: "Gather ReAct",
  agent_prefetch: "聚焦预取",
  agent_compose: "Compose 成稿",
  agent_decision: "决策校验",
  prompt_build: "组装模型上下文",
  model_response: "流式模型回复",
};

export function PipelinePanel({ steps }: { steps: PipelineStep[] }) {
  if (!steps.length) {
    return <div className="text-xs text-slate-500 bg-white border rounded-2xl p-3">发起对话后会展示端侧、云端、规则和模型调用链路。</div>;
  }
  return (
    <div className="rounded-2xl bg-white border border-slate-100 p-3 space-y-2">
      <div className="text-xs font-semibold text-slate-700">本次服务链路</div>
      {steps.map((step) => (
        <div key={`${step.name}-${step.detail}`} className="flex items-center gap-2 text-xs">
          <span className="w-2 h-2 rounded-full bg-emerald-500" />
          <span className="font-medium">{names[step.name] ?? step.name}</span>
          {step.detail && <span className="text-slate-500">· {step.detail}</span>}
        </div>
      ))}
    </div>
  );
}

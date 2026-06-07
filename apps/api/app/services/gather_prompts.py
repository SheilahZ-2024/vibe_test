"""Gather 阶段 Prompt — 有界 ReAct：模型主导查规则、选工具、收 observation。"""

from __future__ import annotations

from app.config import settings
from app.diagnosis.storybook import oral_expression_guidance
from app.services.agent_state import AgentState, AgentTraceStep
from app.services.context import context_summary_for_agent
from app.services.conversation_memory import format_memory_block
from app.services.diagnosis_rules import prompt_rules_block, should_include_oral_guidance
from app.services.fact_sheet import build_fact_sheet, format_fact_sheet_block
from app.services.intent import IntentResult
from app.services.tool_catalog import TOOL_CATALOG, tool_catalog_block
from app.services.turn_plan import TurnPlan

GATHER_MISSION = """你是抖音生活服务 AI 履约管家的 **Gather 核实专员**。

本阶段职责（仅此阶段，不写用户终稿）：
1. 判断用户问题涉及哪些**平台规则/资格**（预约、核销、退款、门店营业等）
2. 决定需要哪些**只读工具**拉取数据，或调用 **run_diagnosis** 对照诊断脚本
3. 每步根据 observation 决定下一步，或输出 **gather_complete** 结束 Gather

原则：
- 双轨参考：规则层（prompt 中的规则块）+ 诊断脚本（run_diagnosis）并行，须交叉验证
- 信息不足 / 多订单未聚焦 → 先 list_orders 或 gather_complete 并写明 missing_info
- **禁止编造**；禁止在本阶段写用户回复正文
- 已有会话记忆且事实足够 → 可少查甚至直接 gather_complete
- 有 focus_order_id 时优先 query_focus_bundle，勿重复 query_order/query_voucher/query_store
- 写操作（退款/预约/转人工等）**不在 Gather 执行**；若需要，gather_complete 时在 missing_info 或 gather_summary 注明

效率：一般 1~3 步内 gather_complete；勿重复相同只读工具。"""

GATHER_OUTPUT_SCHEMA = """输出一个 JSON（无 markdown 包裹）：
{
  "thought": "本步推理：要核实什么规则、为什么选这个工具",
  "rules_to_check": ["预约是否必须", "券是否有效", "…"],
  "action": "工具名 或 gather_complete",
  "action_input": {},
  "focus_order_id": "可选，多订单时指定聚焦",
  "gather_summary": "action=gather_complete 时必填：已核实事实与规则结论摘要",
  "missing_info": ["仍缺的关键信息，无则 []"]
}

action=gather_complete 时不要再调用工具；gather_summary 会交给 Compose 成稿。"""

GATHER_CONTINUATION_HEADER = """继续 Gather ReAct，输出下一步 JSON（格式同上）。
若 observation 已足够回答用户问题，action=gather_complete 并写清 gather_summary。
勿重复已成功的相同只读 query。"""

_READ_ONLY_FOR_GATHER = frozenset(
    name for name, meta in TOOL_CATALOG.items() if meta.get("read_only", True)
)


def gather_tool_catalog_block(
    *,
    intent: str | None = None,
    executed: set[str] | None = None,
    compact: bool = False,
) -> str:
    """Gather 阶段仅暴露只读工具（不含写操作）。"""
    if executed:
        from app.services.tool_catalog import tools_for_continuation

        names = [n for n in tools_for_continuation(intent, executed) if n in _READ_ONLY_FOR_GATHER]
    else:
        from app.services.tool_catalog import tools_for_intent

        names = [n for n in tools_for_intent(intent) if n in _READ_ONLY_FOR_GATHER]
    lines = []
    for name in names:
        meta = TOOL_CATALOG.get(name)
        if not meta:
            continue
        if compact:
            lines.append(f"{name}: {meta['description'][:52]}")
        else:
            params = meta.get("parameters") or {}
            param_text = ", ".join(f"{k}: {v}" for k, v in params.items()) if params else "无"
            lines.append(f"- {name}: {meta['description']}\n  参数: {param_text}")
    lines.append("- gather_complete: 核实完毕，提交 gather_summary 给 Compose（只读阶段结束）")
    return "\n".join(lines) if not compact else " | ".join(lines)


def build_gather_system_prompt(
    state: AgentState,
    plan: TurnPlan,
    history: list[dict],
    *,
    step_idx: int = 0,
) -> str:
    intent = state.intent_result
    if step_idx > 0:
        return _build_gather_continuation_prompt(state, plan)

    rules = prompt_rules_block(plan.route_intent, plan.route_category)
    oral = oral_expression_guidance() if should_include_oral_guidance(plan.route_intent, plan.route_category) else ""
    oral_block = f"\n{oral}\n" if oral else ""

    prior_block = ""
    if state.prior_agent_ctx and plan.reuse_prior_facts:
        prior_block = f"""
── 会话记忆（接话轮次，优先复用，不足再查）──
{format_memory_block(state.prior_agent_ctx)}
"""

    fact_sheet = build_fact_sheet(
        service_context=state.service_context,
        tool_calls=state.tool_calls,
        diagnosis_advisories=state.diagnosis_advisories,
        focus_order_id=state.focus_order_id,
    )
    fact_block = format_fact_sheet_block(fact_sheet)
    facts_section = ""
    if fact_block and fact_block != "（尚无结构化事实）":
        facts_section = f"""
── 已核实事实（Gather 过程中累积，禁止违背）──
{fact_block}
"""

    prefetch_note = ""
    if state.prefetch_done:
        prefetch_note = "\n── 预取 ──\nquery_focus_bundle 已在 ReAct 前执行，可直接 run_diagnosis / search_knowledge / gather_complete。\n"

    return f"""{GATHER_MISSION}

{GATHER_OUTPUT_SCHEMA}

── 本轮路由 ──
task_type={plan.task_type} | intent={plan.route_intent} | turn_mode={plan.turn_mode}
{_intent_line(intent)}
{oral_block}
{rules}
{prefetch_note}{prior_block}{facts_section}
── 可用只读工具 ──
{gather_tool_catalog_block(intent=plan.route_intent, executed=state.executed_tools)}

── 聚焦订单 ──
{state.focus_order_id or "未选；多订单时 list_orders 或在 JSON 中指定 focus_order_id"}

── 用户上下文 ──
{context_summary_for_agent(state.service_context, state.focus_order_id)}

── 知识库（已检索）──
{_knowledge_block(state.knowledge_articles)}

── 诊断脚本（已跑）──
{_diagnosis_block(state.diagnosis_advisories)}

── 会话摘要 ──
{_history_block(history)}
"""


def build_gather_user_prompt(state: AgentState, history: list[dict], plan: TurnPlan, *, step_idx: int) -> str:
    if step_idx == 0:
        recent = "\n".join(f"{m['role']}: {m['content'][:160]}" for m in history[-4:]) or "（首轮）"
        return f"""最近对话：
{recent}

用户最新：{state.message}

请输出 Gather JSON（选择工具或 gather_complete）。"""

    last = state.trace[-1] if state.trace else None
    obs_preview = ""
    if last and last.observation is not None:
        obs_preview = str(last.observation)[: settings.agent_react_observation_limit]
    return f"""上一步 #{last.step if last else '?'} action={last.action if last else '?'}
observation 摘要：
{obs_preview or '（无）'}

请输出下一步 Gather JSON。"""


def build_gather_continuation_system(state: AgentState, plan: TurnPlan) -> str:
    return _build_gather_continuation_prompt(state, plan)


def format_gather_trace_for_compose(trace: list[AgentTraceStep], gather_meta: dict | None) -> str:
    """完整 Gather trace，供 Compose 消费。"""
    if not trace and not gather_meta:
        return "（Gather 未执行或未记录 trace）"
    lines: list[str] = []
    obs_limit = settings.agent_react_observation_limit
    for item in trace:
        obs = item.observation
        if isinstance(obs, dict):
            obs_text = str(obs)[:obs_limit]
        else:
            obs_text = str(obs)[:obs_limit] if obs else ""
        rules = ""
        if isinstance(item.action_input, dict) and item.action_input.get("rules_to_check"):
            rules = f" | rules={item.action_input.get('rules_to_check')}"
        lines.append(
            f"#{item.step} [{item.action}] {item.thought[:160]}{rules}\n  → {obs_text}"
            + (f" [err={item.error}]" if item.error else "")
        )
    meta = gather_meta or {}
    if meta.get("gather_summary"):
        lines.append(f"\n── gather_complete 摘要 ──\n{meta['gather_summary']}")
    if meta.get("rules_to_check"):
        lines.append(f"规则核对清单：{', '.join(str(r) for r in meta['rules_to_check'][:6])}")
    if meta.get("missing_info"):
        lines.append(f"仍缺信息：{', '.join(str(m) for m in meta['missing_info'][:4])}")
    return "\n".join(lines) if lines else "（无 Gather trace）"


def _build_gather_continuation_prompt(state: AgentState, plan: TurnPlan) -> str:
    return f"""{GATHER_CONTINUATION_HEADER}

意图：{plan.route_intent} | 聚焦：{state.focus_order_id or "未选"} | 已执行：{", ".join(sorted(state.executed_tools)) or "无"}

── 剩余只读工具 ──
{gather_tool_catalog_block(intent=plan.route_intent, executed=state.executed_tools, compact=True)}

── 诊断脚本 ──
{_diagnosis_block(state.diagnosis_advisories)}

── 知识库 ──
{_knowledge_block(state.knowledge_articles)}

── 已执行 Gather 步骤 ──
{_trace_block(state.trace)}
"""


def _intent_line(intent: IntentResult) -> str:
    if intent.route_category == "chitchat":
        return f"chitchat（{intent.confidence:.0%}）：可 gather_complete，勿过度查数"
    if intent.route_intent == "clarify":
        return f"clarify（{intent.confidence:.0%}）"
    return f"{intent.route_intent}（{intent.route_category}，{intent.confidence:.0%}）"


def _knowledge_block(articles: list) -> str:
    if not articles:
        return "（尚未检索；政策/FAQ 问题可 search_knowledge）"
    limit = settings.agent_knowledge_content_limit
    lines = []
    for a in articles[:3]:
        if isinstance(a, dict):
            title = a.get("title") or "?"
            body = str(a.get("content") or "")
        else:
            title = getattr(a, "title", "?")
            body = getattr(a, "content", "") or ""
        body = body if len(body) <= limit else body[:limit] + "…"
        lines.append(f"- {title}: {body}")
    return "\n".join(lines)


def _diagnosis_block(advisories: list[dict]) -> str:
    if not advisories:
        return "（未跑 run_diagnosis；资格/故障类问题建议调用）"
    adv = advisories[-1]
    case = adv.get("case_id") or "?"
    name = adv.get("case_name") or ""
    actions = ", ".join(a.get("title", "") for a in (adv.get("solution") or [])[:3])
    return f"Case {case} {name} | 建议: {actions or '无'}（须与 query 交叉验证）"


def _trace_block(trace: list[AgentTraceStep], *, max_steps: int | None = None) -> str:
    if not trace:
        return "（尚无）"
    obs_limit = settings.agent_react_observation_limit
    items = trace[-max_steps:] if max_steps else trace
    lines = []
    for item in items:
        obs = item.observation
        if isinstance(obs, dict):
            obs_text = str(obs)[:obs_limit]
        else:
            obs_text = str(obs)[:obs_limit] if obs else ""
        lines.append(
            f"#{item.step} {item.action}: {item.thought[:120]}\n  → {obs_text}"
            + (f" [err={item.error}]" if item.error else "")
        )
    return "\n".join(lines)


def _history_block(history: list[dict]) -> str:
    if not history:
        return "无"
    trimmed = history[-settings.agent_history_max_turns :]
    return "\n".join(f"{m['role']}: {m['content'][:160]}" for m in trimmed)

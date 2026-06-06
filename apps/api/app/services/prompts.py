"""Agent Prompt 构建 — ReAct 推理与最终回复（分层压缩以降低 token）。"""

from __future__ import annotations

from app.config import settings
from app.diagnosis.storybook import oral_expression_guidance
from app.services.agent_state import AgentState, AgentTraceStep
from app.services.context import context_summary_for_agent
from app.services.diagnosis_rules import prompt_rules_block, should_include_oral_guidance
from app.services.intent import IntentResult
from app.services.tool_catalog import tool_catalog_block

AGENT_MISSION = """你是抖音生活服务 AI 履约服务管家，通过 ReAct（思考→行动→观察）自主决策。
原则：双轨参考（规则层+诊断脚本）并行、你综合裁决；信息不足/多订单未聚焦→finish clarify；
写操作须用户确认；禁止编造数据、盲信任一侧、未聚焦擅自选单。
效率：尽量 2-4 步内 finish；已有 query 结果勿重复调用相同工具；finish 时 draft_message 写完整用户回复。
知识库：需要政策/FAQ 支撑时调用 search_knowledge，自行决定 query 与 limit(1~5)，勿预置假设条数。"""

REACT_OUTPUT_SCHEMA = """输出一个 JSON（无 markdown）：
{"thought":"推理","action":"工具名或finish","action_input":{},"focus_order_id":"可选",
 "finish":{"mode":"reply|clarify","draft_message":"给用户的话","safe_to_send":true/false,
 "reasoning":"…","approved_case_id":null,"approved_case_name":null,
 "suggested_actions":[{"action_id":"…","title":"…"}]}}
action=finish 时 finish 必填；写操作 pending 时用 suggested_actions（最多4个）。"""

REACT_CONTINUATION_HEADER = """继续 ReAct，输出下一步 JSON（格式同上）。
事实已足够则 action=finish 并写好 draft_message；勿重复相同 query。"""


def build_react_system_prompt(state: AgentState, history: list[dict], *, step_idx: int = 1) -> str:
    intent = state.intent_result

    if step_idx > 1:
        return _build_react_continuation_prompt(state)

    knowledge = _knowledge_block(state.knowledge_articles)
    rules = prompt_rules_block(intent.route_intent, intent.route_category)
    oral = oral_expression_guidance() if should_include_oral_guidance(intent.route_intent, intent.route_category) else ""
    oral_block = f"\n{oral}\n" if oral else ""

    return f"""{AGENT_MISSION}

{REACT_OUTPUT_SCHEMA}

── 意图（可参考/修正）──
{_intent_guidance(intent)}
{oral_block}
{rules}

── 可用工具 ──
{tool_catalog_block(intent=intent.route_intent)}

── 聚焦订单 ──
{state.focus_order_id or "未选；多订单时 list_orders 或 finish clarify"}

── 用户上下文 ──
{context_summary_for_agent(state.service_context, state.focus_order_id)}

── 知识库（轨道 A）──
{knowledge}

── 诊断脚本（轨道 B，若有）──
{_diagnosis_script_block(state.diagnosis_advisories)}

── 会话摘要 ──
{_history_block(history)}
"""


def _build_react_continuation_prompt(state: AgentState) -> str:
    route_intent = state.intent_result.route_intent
    return f"""{REACT_CONTINUATION_HEADER}

意图：{route_intent} | 聚焦：{state.focus_order_id or "未选"}

── 工具 ──
{tool_catalog_block(intent=route_intent, compact=True)}

── 诊断脚本（轨道 B）──
{_diagnosis_script_block(state.diagnosis_advisories, compact=True)}

── 知识库（search_knowledge 结果）──
{_knowledge_block(state.knowledge_articles) if state.knowledge_articles else "（未检索）"}

── 已执行步骤 ──
{_trace_block(state.trace)}
"""


def build_final_reply_prompt(state: AgentState, finish: dict) -> str:
    """终轮润色 Prompt（仅在 ReAct 未产出足够 draft 时使用，尽量短）。"""
    mode = finish.get("mode", "reply")
    mode_hint = (
        "澄清模式：只问 1-2 个关键问题。"
        if mode == "clarify"
        else "给出完整可执行回复，自然口语，可用 emoji，不要 markdown 列表。"
    )
    if finish.get("safe_to_send") is False:
        mode_hint = "尚不安全：以澄清/核实为主，不得给确定性结论。"

    draft = (finish.get("draft_message") or "").strip()
    draft_block = f"\n草稿（可润色，勿违背工具事实）：\n{draft}" if draft else ""

    tools = _compact_tool_results(state.tool_calls)
    latest_script = _diagnosis_script_block(state.diagnosis_advisories, compact=True)

    return f"""{AGENT_MISSION}
{mode_hint}

意图：{state.intent_result.route_intent}
聚焦：{state.focus_order_id or "未聚焦"}

── 推理摘要 ──
{_trace_block(state.trace, max_steps=4)}

── 脚本参考 ──
{latest_script}

── 工具结果 ──
{tools}
{draft_block}
"""


def should_use_draft_directly(finish: dict) -> bool:
    if not settings.agent_skip_final_llm_when_draft:
        return False
    draft = (finish.get("draft_message") or "").strip()
    if len(draft) < settings.agent_draft_min_chars:
        return False
    mode = finish.get("mode", "reply")
    if mode == "clarify":
        return True
    return bool(finish.get("safe_to_send", True))


def _knowledge_block(articles: list) -> str:
    if not articles:
        return "（尚未检索；需要政策/FAQ 时调用 search_knowledge，自行决定 query 与 limit）"
    limit = settings.agent_knowledge_content_limit
    lines = []
    for a in articles[:3]:
        body = a.content if len(a.content) <= limit else a.content[:limit] + "…"
        lines.append(f"- [{a.category or 'policy'}] {a.title}: {body}")
    return "\n".join(lines)


def _diagnosis_script_block(advisories: list[dict], *, compact: bool = False) -> str:
    if not advisories:
        return "（未跑 run_diagnosis）" if compact else "（尚未调用 run_diagnosis；可仅凭轨道 A + query 推理）"
    adv = advisories[-1]
    if compact:
        case = adv.get("case_id") or "?"
        actions = ", ".join(a.get("title", "") for a in (adv.get("solution") or [])[:3])
        return f"Case {case} | 推荐: {actions or '无'}（须与 query 交叉验证）"
    return _format_diagnosis(adv)


def _intent_guidance(intent_result: IntentResult) -> str:
    if intent_result.route_category == "unconfigured":
        return f"unconfigured（{intent_result.confidence:.0%}）：说明边界，引导履约说法或转人工"
    if intent_result.route_category == "chitchat":
        return f"chitchat（{intent_result.confidence:.0%}）：简短寒暄后引导描述履约问题，可 finish 不调工具"
    if intent_result.route_intent == "clarify":
        alts = "、".join(f"{a['intent']}" for a in intent_result.alternatives[:2])
        return f"clarify（{intent_result.confidence:.0%}）{('，可能：' + alts) if alts else ''}"
    return f"{intent_result.route_intent}（{intent_result.route_category}，{intent_result.confidence:.0%}，{intent_result.source}）"


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
    max_turns = settings.agent_history_max_turns
    trimmed = history[-max_turns:]
    return "\n".join(f"{m['role']}: {m['content'][:160]}" for m in trimmed)


def _compact_tool_results(tool_calls: list[dict]) -> str:
    if not tool_calls:
        return "无"
    lines = []
    for t in tool_calls[-6:]:
        name = t.get("name", "?")
        result = t.get("result")
        preview = str(result)[:280] if result is not None else ""
        lines.append(f"- {name}: {preview}")
    return "\n".join(lines)


def _format_diagnosis(adv: dict) -> str:
    steps = adv.get("diagnosis") or []
    step_lines = "\n".join(
        f"  {s.get('step')}. {s.get('check')}: {s.get('status')}" for s in steps[:5]
    )
    actions = adv.get("solution") or []
    action_lines = "\n".join(f"  - {a.get('title')} ({a.get('action_id')})" for a in actions[:3])
    return (
        f"Case: {adv.get('case_id')} {adv.get('case_name')}\n"
        f"步骤:\n{step_lines or '  无'}\n"
        f"推荐:\n{action_lines or '  无'}"
    )

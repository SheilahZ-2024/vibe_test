"""统一 Compose 阶段 Prompt — 单次 LLM 决策 + 成稿。"""

from __future__ import annotations

from app.services.agent_state import AgentState
from app.services.context import context_summary_for_agent
from app.services.conversation_memory import format_memory_block
from app.services.diagnosis_rules import prompt_rules_block
from app.services.fact_sheet import format_fact_sheet_block
from app.services.gather_prompts import format_gather_trace_for_compose
from app.services.turn_plan import TurnPlan

COMPOSE_OUTPUT_SCHEMA = """输出一个 JSON（无 markdown 包裹）：
{
  "understanding": {"user_goal":"…","references_prior_turn":true/false,"ambiguities":[]},
  "reasoning": {
    "facts_used":["fact_sheet中的键名，如 order_title、needs_reservation、store_phone"],
    "rule_application":"如何应用规则/诊断",
    "alternatives_rejected":["未采纳的错误方向…"]
  },
  "self_check": {
    "fact_conflicts":[],
    "missing_info":[],
    "safe_to_send":true/false,
    "confidence":0.0-1.0,
    "needs_clarify":false
  },
  "decision": {
    "mode":"reply|clarify",
    "intent":"Intent名",
    "focus_order_id":"可选"
  },
  "reply":"给用户看的正文：自然口语、像真人客服，**必须含 1~2 个贴切 emoji**（如 😊 📞 ✅ ⚠️），禁止 markdown 列表",
  "suggested_actions":[{"action_id":"…","title":"…"}]
}

硬性要求：
- 只能使用「已核实事实」与诊断/知识库中的信息，禁止编造金额、电话、规则
- needs_reservation=true 时禁止说「未预约也能核销/没有预约要求」
- 信息不足时 mode=clarify，reply 只问 1-2 个关键问题
- suggested_actions 最多 4 个，仅写操作需要用户确认时出现
"""

COMPOSE_MISSION = """你是抖音生活服务 AI 履约管家。

Gather ReAct 阶段已由模型主导完成工具调用与规则核对；下方提供 **完整 Gather trace**、fact_sheet 与诊断结论。
你**不再调用工具**，只做：
1. 理解用户句（含省略、指代、接话）
2. 对照 Gather trace 与事实做推理（写入 reasoning）
3. 自监督检查（self_check）后给出唯一回复 reply

若 Gather 的 missing_info 非空且无法从 trace 推断，mode=clarify。
语气：自然、亲切、像真人客服；2-6 句话；reply 里要有 1~2 个 emoji，贴合场景，勿堆砌。"""


def build_compose_system_prompt(state: AgentState, plan: TurnPlan, fact_block: str) -> str:
    intent = plan.route_intent
    rules = prompt_rules_block(intent, plan.route_category)
    prior = ""
    if state.prior_agent_ctx:
        prior = f"""
── 会话记忆 ──
{format_memory_block(state.prior_agent_ctx)}
"""
    kb = _knowledge_block(state.knowledge_articles)
    diag = _diagnosis_block(state.diagnosis_advisories)
    gather_trace = format_gather_trace_for_compose(state.trace, state.gather_meta)

    return f"""{COMPOSE_MISSION}

{COMPOSE_OUTPUT_SCHEMA}

── 本轮任务 ──
task_type={plan.task_type} | intent={intent} | turn_mode={plan.turn_mode}
{rules}
{prior}
── 已核实事实（禁止违背或超出）──
{fact_block}

── Gather ReAct 完整 trace（含每步 thought / observation / gather_summary）──
{gather_trace}

── 用户上下文摘要 ──
{context_summary_for_agent(state.service_context, state.focus_order_id)}

── 诊断脚本结论 ──
{diag}

── 知识库 ──
{kb}
"""


def build_compose_user_prompt(state: AgentState, history: list[dict], plan: TurnPlan) -> str:
    recent = "\n".join(f"{m['role']}: {m['content'][:160]}" for m in history[-6:]) or "（首轮）"
    return f"""最近对话：
{recent}

用户最新：{state.message}

请输出 JSON。"""


def build_compose_retry_prompt(errors: list[str]) -> str:
    return "上次输出未通过校验：" + "；".join(errors) + "。请修正后重新输出完整 JSON。"


def _knowledge_block(articles: list) -> str:
    if not articles:
        return "（未检索政策 FAQ）"
    lines = []
    for a in articles[:3]:
        if isinstance(a, dict):
            title = a.get("title") or "?"
            body = str(a.get("content") or "")
        else:
            title = getattr(a, "title", "?")
            body = getattr(a, "content", "") or ""
        body = body if len(body) <= 180 else body[:180] + "…"
        lines.append(f"- {title}: {body}")
    return "\n".join(lines)


def _diagnosis_block(advisories: list[dict]) -> str:
    if not advisories:
        return "（未运行诊断或未命中 Case）"
    adv = advisories[-1]
    case = adv.get("case_id") or "?"
    name = adv.get("case_name") or ""
    actions = ", ".join(a.get("title", "") for a in (adv.get("solution") or [])[:3])
    return f"Case {case} {name} | 建议: {actions or '无'}"


def _tool_summary(tool_calls: list[dict]) -> str:
    if not tool_calls:
        return "（本轮未执行工具）"
    parts = []
    for tc in tool_calls[-6:]:
        if not isinstance(tc, dict):
            continue
        name = tc.get("name") or "?"
        parts.append(name)
    return "已执行: " + ", ".join(parts)

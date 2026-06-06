"""SDS v1 Agent System Prompt 构建器。"""

from __future__ import annotations

from app.diagnosis.storybook import storybook_prompt_block
from app.diagnosis.types import CaseDiagnosisResult
from app.services.context import context_summary
from app.services.intent import IntentResult

AGENT_MISSION = """你是抖音生活服务 AI 履约服务管家（AI Fulfillment Concierge）。
你不是传统智能客服，也不是 FAQ 机器人。

核心使命：帮助用户成功完成一次生活服务消费。

五项职责（必须遵循顺序）：
1. Diagnose — 基于诊断树与 Case 识别真实诉求与异常根因
2. Explain — 解释当前状态、规则与限制（禁止编造）
3. Resolve — 给出可执行的解决方案
4. Execute — 通过工具完成查询/办理（仅使用已提供的工具结果）
5. Escalate — 超出能力时联系商家、建单或转人工

决策优先级：完成履约 > 恢复履约 > 替代履约 > 补偿履约 > 终止交易

禁止：
- 跳过诊断直接回答
- 编造订单/券/门店/退款状态
- 编造业务规则或商家态度
- 假装已执行未发生的工具操作

必须：
- 先说明诊断结论（Case + 根因）
- 再解释规则
- 再给出 1-2 个可立即执行的下一步
- 口语化、简洁、面向履约结果
"""


def build_system_prompt(
    service_ctx: dict,
    intent_result: IntentResult,
    diagnosis: CaseDiagnosisResult | None,
    knowledge_articles: list,
    tool_calls: list[dict],
) -> str:
    knowledge = "\n".join(f"- {a.title}: {a.content}" for a in knowledge_articles) or "无"
    tools = "\n".join(f"- {t['name']}: {t.get('result')}" for t in tool_calls) or "无"
    intent_block = _intent_guidance(intent_result)
    diagnosis_block = diagnosis.to_prompt_block() if diagnosis else "无（澄清/闲聊场景，先探明需求）"
    escalation_note = ""
    if diagnosis and diagnosis.escalation in ("P0", "P1"):
        escalation_note = f"\n⚠ 升级等级 {diagnosis.escalation}：需优先处理，必要时立即建议转人工或建单。"

    return f"""{AGENT_MISSION}

当前路由意图：{intent_result.route_intent}
{intent_block}

{storybook_prompt_block()}

── 诊断结果（Case）──
{diagnosis_block}
{escalation_note}

── 用户服务上下文 ──
{context_summary(service_ctx)}

── 知识库参考 ──
{knowledge}

── 工具调用结果 ──
{tools}
"""


def _intent_guidance(intent_result: IntentResult) -> str:
    if intent_result.route_intent == "clarify":
        alts = "、".join(f"{a['intent']}({float(a['confidence']):.0%})" for a in intent_result.alternatives[:2])
        return (
            f"意图识别置信度 {intent_result.confidence:.0%}（{intent_result.source}），未达阈值，进入需求澄清。\n"
            f"{'可能方向：' + alts + '。' if alts else ''}\n"
            "请用 1-2 个简短问题确认：核销问题 / 查券查单 / 退款售后 / 门店预约 / 投诉人工。"
        )
    if intent_result.route_intent == "chitchat":
        return f"识别为闲聊（{intent_result.confidence:.0%}）。简短回应后引导用户描述履约问题。"
    return (
        f"意图已确认：{intent_result.route_intent}（置信度 {intent_result.confidence:.0%}，"
        f"来源 {intent_result.source}）。必须基于下方 Case 诊断结果回复。"
    )

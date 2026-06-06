"""诊断树规则与双轨参考模型 — 供大模型理解、思考、判断。"""

# 大模型决策时的双轨参考模型（规则文本 vs 诊断脚本产出）
DUAL_REFERENCE_MODEL = """
── 双轨参考模型（核心架构，每步 thought 须体现如何综合）──

你有两路并行、彼此独立的参考输入，都不是「最终答案」，需由你在 thought 中理解、交叉验证后再决定下一步：

【轨道 A · 规则层 · 同步可读】
- 来源：下方「诊断树规则」+「知识库业务规则」+ 口语理解指引
- 性质：静态业务规则与判别节点说明，供你建模推理「应该查什么、可能是什么问题」
- 用法：在调用 run_diagnosis 之前即可阅读并指导 query/list 等动作；与脚本结果不一致时，以真实 query 数据 + 规则共同 adjudicate

【轨道 B · 诊断脚本层 · 异步执行】
- 来源：你主动调用 run_diagnosis 工具后返回的结构化 Case / 诊断步骤 / 推荐动作
- 性质：诊断引擎脚本对当前聚焦订单的一次演算结果，可能与规则层推断一致或不一致
- 用法：仅作参考因子；返回后写入 observation，你必须在下一步 thought 中说明是否采纳、为何采纳或为何质疑

【综合决策】
- 规则层与脚本层不是主从关系，而是两个并行参考；你才是裁判
- 任一路与 query 工具结果或用户描述矛盾 → finish clarify 或继续 query，禁止盲信任一路
- 可在未跑 run_diagnosis 时仅凭规则层 + query 回复；也可跑脚本后仍拒绝其 Case
- suggested_actions / approved_case_id 必须在你综合两轨 + 工具事实并 safe_to_send 后才填写
"""

DIAGNOSIS_TREE_RULES = """
── 诊断树规则（轨道 A · 供理解推理，非自动执行脚本）──

何时考虑调用 run_diagnosis（轨道 B 异步脚本）：
- 已有聚焦订单，意图属核销/退款/门店/预约/投诉等
- 已通过 list_orders / query_* 掌握基本事实，仍需要脚本化 Case 建议作对照
- 不应在：多订单未聚焦、用户描述与数据严重矛盾、纯闲聊时调用

核销受阻（VoucherUnavailable）判别节点 — 请结合 query 数据逐步核对：
1. 订单/券是否存在 → 不存在则查支付/出单
2. 券是否过期、是否已核销
3. 门店是否匹配、是否营业、是否需预约且未预约
4. 商家是否拒核销（须与用户描述交叉验证）
5. 系统/扫码异常（metadata 仅作线索）
6. 任一步信息不足或与用户说法矛盾 → clarify，勿强行定 Case

查询类 / 售后类：
- 先聚焦订单，再 query_order / query_voucher / query_refund

脚本产出采纳原则（轨道 B 返回后）：
- Case ID 是标签不是回复模板；与事实不符必须 clarify
- 脚本推荐动作不等于已执行；写操作须用户确认
- 规则层推断与脚本 Case 不一致时，在 thought 中解释取舍
"""

_VOUCHER_DIAGNOSIS_RULES = """
核销受阻（VoucherUnavailable）判别节点 — 请结合 query 数据逐步核对：
1. 订单/券是否存在 → 不存在则查支付/出单
2. 券是否过期、是否已核销
3. 门店是否匹配、是否营业、是否需预约且未预约（看 usage_rule + 订单 metadata）
4. 商家是否拒核销（须与用户描述交叉验证）
5. 系统/扫码异常（metadata 仅作线索）
6. 任一步信息不足或与用户说法矛盾 → clarify，勿强行定 Case
"""

_QUERY_DIAGNOSIS_RULES = """
查询类 / 售后类：
- 先聚焦订单，再 query_order / query_voucher / query_refund
- 预约问题：看券 usage_rule 是否「须预约」，订单 metadata 是否有 reservation_confirmed
"""

_CLARIFY_RULES = """
── 规则（澄清/闲聊）──
引导用户描述具体履约问题（订单、券码、核销、预约、退款）；勿编造订单事实。
多订单时 list_orders 或 finish clarify。
"""

_DUAL_REFERENCE_COMPACT = """
双轨参考：轨道 A=下方规则+query 事实；轨道 B=run_diagnosis 脚本（可选，须交叉验证）。
你是裁判，任一路与 query 矛盾 → clarify 或继续 query。
"""


def prompt_rules_block(route_intent: str | None, route_category: str | None) -> str:
    """按意图注入规则片段，避免每轮塞满整棵诊断树。"""
    category = route_category or ""
    intent = route_intent or ""

    if category in ("chitchat", "unconfigured") or intent in ("clarify",):
        return _CLARIFY_RULES

    if intent in (
        "VoucherUnavailable",
        "MerchantReject",
        "StoreUnavailable",
        "ReservationFailure",
        "QueryReservation",
        "CheckReservationEligibility",
    ):
        return f"{_DUAL_REFERENCE_COMPACT}\n{_VOUCHER_DIAGNOSIS_RULES}\n何时可调用 run_diagnosis：聚焦订单且 query 后仍需 Case 对照。"

    if intent.startswith("Query") or intent in ("RefundRequest", "QueryRefund", "HumanTransfer"):
        return f"{_DUAL_REFERENCE_COMPACT}\n{_QUERY_DIAGNOSIS_RULES}"

    return f"{_DUAL_REFERENCE_COMPACT}\n{DIAGNOSIS_TREE_RULES}"


def should_include_oral_guidance(route_intent: str | None, route_category: str | None) -> bool:
    if (route_category or "") in ("chitchat", "unconfigured"):
        return False
    intent = route_intent or ""
    if intent in ("clarify",):
        return True
    return intent not in ("QueryOrder", "QueryCoupon", "QueryTicket", "QueryRefund")

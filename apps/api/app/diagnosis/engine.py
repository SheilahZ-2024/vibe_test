"""SDS v1 诊断引擎 — 70 Case 全量路由与诊断树。"""

from __future__ import annotations

from datetime import datetime, timezone

from app.diagnosis.matrices import resolve_actions
from app.diagnosis.registry import CASE_REGISTRY, INTENT_TO_DEFAULT_CASE
from app.diagnosis.storybook import match_case_hint
from app.diagnosis.types import CaseDiagnosisResult, DiagnosisContext, DiagnosisStep


def _meta(obj: dict | None) -> dict:
    return obj if isinstance(obj, dict) else {}


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _has_reservation(order: dict | None) -> bool:
    meta = _meta(order)
    return bool(meta.get("reservation_confirmed") or meta.get("appointment"))


class DiagnosisEngine:
    def diagnose(self, intent: str, ctx: DiagnosisContext) -> CaseDiagnosisResult:
        msg = ctx.message

        # Storybook 强提示路由
        hint = match_case_hint(msg)
        if hint and intent in ("clarify", hint[0], "VoucherUnavailable", "QueryOrder", "ServiceMismatch"):
            hinted_intent, case_id = hint
            if intent == "clarify":
                intent = hinted_intent
            return self._from_case(
                case_id,
                intent,
                ctx,
                [DiagnosisStep(1, "Storybook匹配", "pass", f"口语映射至 {case_id}", None, case_id)],
                "high",
            )

        if intent in ("clarify", "chitchat"):
            case_id = "CLARIFY" if intent == "clarify" else "CHITCHAT"
            return self._from_case(case_id, intent, ctx, [], "medium")

        if intent == "HumanTransfer":
            return self._from_case("HUMAN", intent, ctx, [DiagnosisStep(1, "用户请求", "pass", "转人工")], "high")

        # Intent 路由
        routers = {
            "VoucherUnavailable": self._diagnose_voucher_unavailable,
            "RefundRequest": self._diagnose_refund_request,
            "QueryRefund": self._diagnose_refund_query,
            "QueryCoupon": self._diagnose_coupon,
            "CheckVoucherAvailability": self._diagnose_coupon,
            "MerchantReject": lambda c: self._diagnose_merchant_issue(c, "MerchantReject", msg),
            "ServiceMismatch": lambda c: self._diagnose_merchant_issue(c, "ServiceMismatch", msg),
            "StoreUnavailable": self._diagnose_store_unavailable,
            "ReservationFailure": self._diagnose_reservation_failure,
            "CompensationRequest": self._diagnose_compensation,
            "AppealRequest": self._diagnose_appeal,
            "SafetyComplaint": self._diagnose_safety,
            "MerchantComplaint": lambda c: self._diagnose_complaint(c, "MerchantComplaint", msg),
            "ServiceComplaint": lambda c: self._diagnose_complaint(c, "ServiceComplaint", msg),
            "PriceDispute": lambda c: self._diagnose_complaint(c, "PriceDispute", msg),
            "QueryOrder": self._diagnose_query_order,
            "QueryVoucher": self._diagnose_query_voucher,
            "QueryStore": self._diagnose_query_store,
            "QueryReservation": self._diagnose_query_reservation,
            "QueryTicket": self._diagnose_query_ticket,
            "CheckRefundEligibility": self._diagnose_refund_request,
            "CheckReservationEligibility": self._diagnose_query_reservation,
        }

        router = routers.get(intent)
        if router:
            return router(ctx)

        default = INTENT_TO_DEFAULT_CASE.get(intent, "IC-001")
        return self._from_case(default, intent, ctx, [DiagnosisStep(1, "默认路由", "pass", default)], "medium")

    # ── 查询类 IC ──

    def _diagnose_query_order(self, ctx: DiagnosisContext) -> CaseDiagnosisResult:
        o = ctx.order
        if not o and not ctx.orders:
            return self._from_case("IC-002", "QueryOrder", ctx, [DiagnosisStep(1, "订单存在", "fail", "未找到订单")], "high")
        if o and o.get("status") == "paid_pending_voucher":
            return self._from_case("PC-001", "QueryOrder", ctx, [DiagnosisStep(1, "出单状态", "fail", "已支付未出券")], "high")
        if o and _meta(o).get("duplicate_order"):
            return self._from_case("PC-003", "QueryOrder", ctx, [DiagnosisStep(1, "重复订单", "warning", "检测到重复下单")], "medium")
        if any(k in ctx.message for k in ("详情", "套餐内容", "包含什么")):
            return self._from_case("IC-003", "QueryOrder", ctx, [DiagnosisStep(1, "查询类型", "pass", "订单详情")], "high")
        return self._from_case("IC-001", "QueryOrder", ctx, [DiagnosisStep(1, "订单状态", "pass", o.get("status", "unknown") if o else "ok")], "high")

    def _diagnose_query_voucher(self, ctx: DiagnosisContext) -> CaseDiagnosisResult:
        if any(k in ctx.message for k in ("券码", "二维码", "码在哪")):
            return self._from_case("IC-005", "QueryVoucher", ctx, [DiagnosisStep(1, "查询类型", "pass", "券码查询")], "high")
        if any(k in ctx.message for k in ("有效期", "什么时候过期", "还能用吗")):
            if ctx.voucher and _parse_dt(ctx.voucher.get("valid_to")) and _parse_dt(ctx.voucher["valid_to"]) <= _now():
                return self._from_case("PC-005", "QueryVoucher", ctx, [DiagnosisStep(1, "有效期", "fail", "已过期")], "high")
            return self._from_case("IC-006", "QueryVoucher", ctx, [DiagnosisStep(1, "查询类型", "pass", "有效期查询")], "high")
        return self._from_case("IC-004", "QueryVoucher", ctx, [DiagnosisStep(1, "券状态", "pass", ctx.voucher.get("status") if ctx.voucher else "-")], "high")

    def _diagnose_query_store(self, ctx: DiagnosisContext) -> CaseDiagnosisResult:
        sm = _meta(ctx.store)
        if sm.get("relocated") or "搬" in ctx.message:
            return self._from_case("FC-003", "QueryStore", ctx, [DiagnosisStep(1, "门店", "warning", "门店已搬迁")], "high")
        if sm.get("phone_unreachable") or "打不通" in ctx.message:
            return self._from_case("FC-004", "QueryStore", ctx, [DiagnosisStep(1, "联系", "fail", "电话无法接通")], "medium")
        return self._from_case("IC-008", "QueryStore", ctx, [DiagnosisStep(1, "门店信息", "pass", "查询营业信息")], "high")

    def _diagnose_query_reservation(self, ctx: DiagnosisContext) -> CaseDiagnosisResult:
        if _meta(ctx.order).get("reservation_required") and not _has_reservation(ctx.order):
            return self._from_case("PC-010", "QueryReservation", ctx, [DiagnosisStep(1, "预约", "fail", "未预约")], "high")
        return self._from_case("IC-009", "QueryReservation", ctx, [DiagnosisStep(1, "预约", "pass", "查询预约状态")], "high")

    def _diagnose_query_ticket(self, ctx: DiagnosisContext) -> CaseDiagnosisResult:
        return self._from_case("AC-008", "QueryTicket", ctx, [DiagnosisStep(1, "工单", "pass", "查询补偿/工单进度")], "high")

    # ── 售后 AC ──

    def _diagnose_refund_request(self, ctx: DiagnosisContext) -> CaseDiagnosisResult:
        o = ctx.order
        steps: list[DiagnosisStep] = []
        if not o:
            return self._from_case("IC-002", "RefundRequest", ctx, [DiagnosisStep(1, "订单", "fail", "未找到")], "medium")
        steps.append(DiagnosisStep(1, "订单存在", "pass", o.get("id", "")))
        if any(k in ctx.message for k in ("部分", "没体验完", "只用了")):
            steps.append(DiagnosisStep(2, "履约程度", "warning", "部分履约"))
            return self._from_case("AC-003", "RefundRequest", ctx, steps, "high")
        if o.get("status") in ("unused", "paid") and o.get("can_refund"):
            steps.append(DiagnosisStep(2, "退款规则", "pass", "未核销可退"))
            return self._from_case("AC-001", "RefundRequest", ctx, steps, "high")
        if o.get("status") in ("redeemed", "used", "consumed"):
            steps.append(DiagnosisStep(2, "退款规则", "fail", "已核销需审核"))
            return self._from_case("AC-002", "RefundRequest", ctx, steps, "high")
        if o.get("status") == "refunding":
            return self._from_case("AC-004", "RefundRequest", ctx, [DiagnosisStep(2, "退款", "pass", "处理中")], "high")
        if _meta(o).get("special_after_sale"):
            return self._from_case("AC-010", "RefundRequest", ctx, [DiagnosisStep(2, "特殊售后", "warning", "需人工审核")], "medium")
        return self._from_case("AC-002", "RefundRequest", ctx, [DiagnosisStep(2, "退款规则", "fail", "不支持自助退")], "medium")

    def _diagnose_refund_query(self, ctx: DiagnosisContext) -> CaseDiagnosisResult:
        r = ctx.refund or {}
        st = r.get("status", "")
        if st == "processing":
            return self._from_case("AC-004", "QueryRefund", ctx, [DiagnosisStep(1, "进度", "pass", "处理中")], "high")
        if st in ("timeout", "delayed"):
            return self._from_case("AC-005", "QueryRefund", ctx, [DiagnosisStep(1, "进度", "fail", "超时")], "high")
        if st == "failed":
            return self._from_case("AC-006", "QueryRefund", ctx, [DiagnosisStep(1, "进度", "fail", "失败")], "high")
        return self._from_case("IC-010", "QueryRefund", ctx, [DiagnosisStep(1, "进度", "pass", "查询")], "high")

    def _diagnose_compensation(self, ctx: DiagnosisContext) -> CaseDiagnosisResult:
        if any(k in ctx.message for k in ("进度", "到哪了", "审核")):
            return self._from_case("AC-008", "CompensationRequest", ctx, [DiagnosisStep(1, "补偿", "pass", "进度查询")], "high")
        return self._from_case("AC-007", "CompensationRequest", ctx, [DiagnosisStep(1, "补偿", "pass", "申请补偿")], "high")

    def _diagnose_appeal(self, ctx: DiagnosisContext) -> CaseDiagnosisResult:
        if any(k in ctx.message for k in ("投诉过", "又投诉", "没人管", "好几次")):
            return self._from_case("CC-015", "AppealRequest", ctx, [DiagnosisStep(1, "申诉", "fail", "重复投诉升级")], "high")
        if any(k in ctx.message for k in ("平台处理", "处理结果", "不公平")):
            return self._from_case("CC-014", "AppealRequest", ctx, [DiagnosisStep(1, "申诉", "pass", "平台结果复核")], "medium")
        if any(k in ctx.message for k in ("退款失败", "退不了")):
            return self._from_case("AC-006", "AppealRequest", ctx, [DiagnosisStep(1, "申诉", "fail", "退款失败")], "high")
        return self._from_case("AC-009", "AppealRequest", ctx, [DiagnosisStep(1, "申诉", "pass", "用户申诉")], "medium")

    # ── 投诉 CC / 安全 ──

    def _diagnose_safety(self, ctx: DiagnosisContext) -> CaseDiagnosisResult:
        msg = ctx.message
        if any(k in msg for k in ("吃坏", "异物", "变质", "中毒", "食品")):
            return self._from_case("CC-008", "SafetyComplaint", ctx, [DiagnosisStep(1, "安全", "fail", "食品安全")], "high")
        return self._from_case("CC-009", "SafetyComplaint", ctx, [DiagnosisStep(1, "安全", "fail", "人身安全")], "high")

    def _diagnose_complaint(self, ctx: DiagnosisContext, intent: str, msg: str) -> CaseDiagnosisResult:
        mapping: list[tuple[tuple[str, ...], str]] = [
            (("虚假宣传", "图片假", "骗人"), "CC-002"),
            (("和宣传不符", "货不对板", "缩水", "少给"), "CC-001"),
            (("态度", "凶", "爱答不理"), "CC-003"),
            (("服务质量", "体验差", "不专业"), "CC-004"),
            (("强制", "最低消费"), "CC-005"),
            (("加价", "多收"), "CC-006"),
            (("拒绝履约", "不给用", "不让进"), "CC-007"),
            (("违规", "举报"), "CC-010"),
            (("权益", "受损"), "CC-011"),
            (("价格", "争议", "乱收费"), "CC-012"),
            (("恶意", "黑店"), "CC-013"),
        ]
        for keys, case_id in mapping:
            if any(k in msg for k in keys):
                return self._from_case(case_id, intent, ctx, [DiagnosisStep(1, "投诉类型", "fail", case_id)], "high")
        default = {"MerchantComplaint": "CC-001", "ServiceComplaint": "CC-003", "PriceDispute": "CC-012"}.get(intent, "CC-003")
        return self._from_case(default, intent, ctx, [DiagnosisStep(1, "投诉", "pass", default)], "medium")

    # ── 履约 FC / 平台 PC ──

    def _diagnose_voucher_unavailable(self, ctx: DiagnosisContext) -> CaseDiagnosisResult:
        v, o, s = ctx.voucher, ctx.order, ctx.store
        steps: list[DiagnosisStep] = []

        if not v:
            steps.append(DiagnosisStep(1, "券是否存在", "fail", "未找到券", "VoucherMissing", "PC-004"))
            return self._from_case("PC-004", "VoucherUnavailable", ctx, steps, "high")
        steps.append(DiagnosisStep(1, "券是否存在", "pass", str(v.get("id"))))

        if not o or o.get("status") in ("cancelled", "invalid", "closed"):
            steps.append(DiagnosisStep(2, "订单有效", "fail", "订单异常", "OrderStatusInvalid", "PC-002"))
            return self._from_case("PC-002", "VoucherUnavailable", ctx, steps, "high")
        if o.get("status") == "paid_pending_voucher":
            steps.append(DiagnosisStep(2, "订单有效", "fail", "已支付未出券", "OrderMissing", "PC-001"))
            return self._from_case("PC-001", "VoucherUnavailable", ctx, steps, "high")
        steps.append(DiagnosisStep(2, "订单有效", "pass", o.get("status", "")))

        valid_to = _parse_dt(v.get("valid_to"))
        if (valid_to and valid_to <= _now()) or v.get("status") == "expired":
            steps.append(DiagnosisStep(3, "券过期", "fail", "已过期", "VoucherExpired", "PC-005"))
            return self._from_case("PC-005", "VoucherUnavailable", ctx, steps, "high")
        steps.append(DiagnosisStep(3, "券过期", "pass", "有效"))

        if v.get("status") in ("redeemed", "used", "consumed"):
            steps.append(DiagnosisStep(4, "券核销", "fail", "已核销", "VoucherRedeemed", "PC-006"))
            return self._from_case("PC-006", "VoucherUnavailable", ctx, steps, "high")
        steps.append(DiagnosisStep(4, "券核销", "pass", v.get("status", "")))

        om, vm, sm = _meta(o), _meta(v), _meta(s)
        if om.get("store_mismatch") or vm.get("store_mismatch"):
            steps.append(DiagnosisStep(5, "门店匹配", "fail", "不适用", "VoucherStoreMismatch", "PC-008"))
            return self._from_case("PC-008", "VoucherUnavailable", ctx, steps, "high")
        steps.append(DiagnosisStep(5, "门店匹配", "pass", "ok"))

        if vm.get("time_restricted") and vm.get("allowed_now") is False:
            steps.append(DiagnosisStep(6, "时段规则", "fail", "当前时段不可用", "VoucherTimeMismatch", "PC-009"))
            return self._from_case("PC-009", "VoucherUnavailable", ctx, steps, "high")
        steps.append(DiagnosisStep(6, "时段规则", "pass", "ok"))

        if om.get("reservation_required") and not _has_reservation(o):
            steps.append(DiagnosisStep(7, "预约", "fail", "需预约", "ReservationMissing", "PC-010"))
            return self._from_case("PC-010", "VoucherUnavailable", ctx, steps, "high")
        steps.append(DiagnosisStep(7, "预约", "pass", "ok"))

        biz = sm.get("business_status", "open")
        if biz == "permanently_closed":
            steps.append(DiagnosisStep(8, "门店营业", "fail", "永久闭店", "StoreClosed", "FC-002"))
            return self._from_case("FC-002", "VoucherUnavailable", ctx, steps, "high")
        if biz in ("suspended", "closed"):
            steps.append(DiagnosisStep(8, "门店营业", "fail", "暂停营业", "StoreSuspended", "FC-001"))
            return self._from_case("FC-001", "VoucherUnavailable", ctx, steps, "high")
        if sm.get("early_closure"):
            steps.append(DiagnosisStep(8, "门店营业", "fail", "提前结束营业", "EarlyClosure", "FC-019"))
            return self._from_case("FC-019", "VoucherUnavailable", ctx, steps, "high")
        steps.append(DiagnosisStep(8, "门店营业", "pass", "ok"))

        if sm.get("merchant_reject") or om.get("merchant_reject"):
            steps.append(DiagnosisStep(9, "商家接待", "fail", "拒绝核销", "MerchantRejectService", "FC-006"))
            return self._from_case("FC-006", "VoucherUnavailable", ctx, steps, "high")
        if any(k in ctx.message for k in ("老板不给", "不让用", "活动结束", "拒绝核销")):
            case = "FC-007" if "活动结束" in ctx.message else "FC-006"
            steps.append(DiagnosisStep(9, "商家接待", "fail", "用户描述拒核销", "MerchantRejectService", case))
            return self._from_case(case, "VoucherUnavailable", ctx, steps, "medium")
        steps.append(DiagnosisStep(9, "商家接待", "pass", "ok"))

        if v.get("status") == "frozen":
            steps.append(DiagnosisStep(10, "系统状态", "fail", "券冻结", "VoucherFrozen", "PC-007"))
            return self._from_case("PC-007", "VoucherUnavailable", ctx, steps, "high")
        if vm.get("qr_invalid") or sm.get("scanner_synced") is False:
            steps.append(DiagnosisStep(10, "系统状态", "warning", "扫码/二维码异常", "SystemVerificationFailed", "FC-008"))
            return self._from_case("FC-008", "VoucherUnavailable", ctx, steps, "medium")
        if om.get("campaign_ended"):
            steps.append(DiagnosisStep(10, "活动", "fail", "活动结束", "CampaignEnded", "PC-015"))
            return self._from_case("PC-015", "VoucherUnavailable", ctx, steps, "high")
        steps.append(DiagnosisStep(10, "系统状态", "pass", "ok"))
        return self._from_case("FC-008", "VoucherUnavailable", ctx, steps, "low")

    def _diagnose_merchant_issue(self, ctx: DiagnosisContext, intent: str, msg: str) -> CaseDiagnosisResult:
        checks: list[tuple[tuple[str, ...], str]] = [
            (("缩水", "少给", "不一样", "缺菜", "缺项"), "FC-011"),
            (("强制", "必须买", "最低消费"), "FC-016"),
            (("加价", "多收", "涨价"), "FC-017"),
            (("缺货", "没货", "卖完"), "FC-013"),
            (("质量差", "体验差", "不专业"), "FC-014"),
            (("态度", "凶", "骂人"), "FC-015"),
            (("没人", "缺席", "不管"), "FC-018"),
            (("接待", "不让进", "拒绝接待"), "FC-012"),
            (("活动结束",), "FC-007"),
            (("老板不给", "不给用", "拒绝核销"), "FC-006"),
        ]
        for keys, case_id in checks:
            if any(k in msg for k in keys):
                return self._from_case(case_id, intent, ctx, [DiagnosisStep(1, "履约异常", "fail", case_id)], "high")
        if _meta(ctx.store).get("insufficient_capacity"):
            return self._from_case("FC-020", intent, ctx, [DiagnosisStep(1, "容量", "fail", "履约能力不足")], "medium")
        return self._from_case("FC-011", intent, ctx, [DiagnosisStep(1, "履约", "warning", "服务不符")], "medium")

    def _diagnose_store_unavailable(self, ctx: DiagnosisContext) -> CaseDiagnosisResult:
        sm = _meta(ctx.store)
        msg = ctx.message
        if sm.get("relocated") or "搬" in msg:
            return self._from_case("FC-003", "StoreUnavailable", ctx, [DiagnosisStep(1, "门店", "warning", "搬迁")], "high")
        if sm.get("phone_unreachable") or "打不通" in msg:
            return self._from_case("FC-004", "StoreUnavailable", ctx, [DiagnosisStep(1, "联系", "fail", "电话不通")], "medium")
        if sm.get("over_capacity") or any(k in msg for k in ("排队", "等太久")):
            return self._from_case("FC-005", "StoreUnavailable", ctx, [DiagnosisStep(1, "容量", "fail", "超负荷")], "medium")
        if sm.get("business_status") == "permanently_closed":
            return self._from_case("FC-002", "StoreUnavailable", ctx, [DiagnosisStep(1, "营业", "fail", "永久闭店")], "high")
        return self._from_case("FC-001", "StoreUnavailable", ctx, [DiagnosisStep(1, "营业", "fail", "暂停营业")], "high")

    def _diagnose_reservation_failure(self, ctx: DiagnosisContext) -> CaseDiagnosisResult:
        if any(k in ctx.message for k in ("不给约", "拒绝预约")):
            return self._from_case("FC-010", "ReservationFailure", ctx, [DiagnosisStep(1, "预约", "fail", "商家拒绝")], "high")
        return self._from_case("FC-009", "ReservationFailure", ctx, [DiagnosisStep(1, "预约", "fail", "无容量")], "medium")

    def _diagnose_coupon(self, ctx: DiagnosisContext, intent: str) -> CaseDiagnosisResult:
        c = ctx.coupon
        if not c:
            return self._from_case("IC-007", intent, ctx, [DiagnosisStep(1, "券", "fail", "未找到")], "medium")
        if _parse_dt(c.get("valid_to")) and _parse_dt(c["valid_to"]) <= _now():
            return self._from_case("PC-012", intent, ctx, [DiagnosisStep(1, "过期", "fail", "优惠券过期")], "high")
        rt = str(c.get("rule_text", ""))
        if c.get("status") == "unavailable" and "门槛" in rt:
            return self._from_case("PC-013", intent, ctx, [DiagnosisStep(1, "门槛", "fail", rt)], "high")
        if "叠加" in rt:
            return self._from_case("PC-014", intent, ctx, [DiagnosisStep(1, "叠加", "fail", rt)], "high")
        return self._from_case("IC-007", intent, ctx, [DiagnosisStep(1, "状态", "pass", rt or "可用")], "high")

    def _from_case(self, case_id: str, intent: str, ctx: DiagnosisContext, steps: list[DiagnosisStep], confidence: str) -> CaseDiagnosisResult:
        case = CASE_REGISTRY.get(case_id) or CASE_REGISTRY["IC-001"]
        if case_id not in CASE_REGISTRY:
            case_id = "IC-001"
        actions = resolve_actions(case_id, case.actions)
        rules = [s.rule for s in steps if s.rule] or list(case.rules)
        return CaseDiagnosisResult(
            intent=intent,
            case_id=case_id,
            case_name=case.name,
            problem_space=case.problem_space,
            user_goal=case.user_goal,
            confidence=confidence,
            escalation=case.escalation,
            triggered_rules=rules,
            steps=steps,
            actions=actions,
            context_snapshot={
                "order_id": (ctx.order or {}).get("id"),
                "voucher_id": (ctx.voucher or {}).get("id"),
                "store_id": (ctx.store or {}).get("id"),
            },
        )

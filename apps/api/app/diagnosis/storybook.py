"""Storybook 全量口语表达库 SB-001 ~ SB-018。"""

from __future__ import annotations

STORYBOOK: dict[str, dict] = {
    "SB-001": {
        "intents": ["QueryOrder"],
        "cases": ["IC-001", "IC-002"],
        "expressions": [
            "帮我看看订单", "我买的东西去哪了", "订单找不到了", "刚买成功了吗",
            "我是不是付款成功了", "怎么看订单", "我的团购呢", "查一下最近订单",
        ],
    },
    "SB-002": {
        "intents": ["QueryVoucher", "CheckVoucherAvailability"],
        "cases": ["IC-004", "IC-005", "IC-006"],
        "expressions": [
            "我的券在哪", "券怎么找", "帮我看看券", "二维码在哪", "怎么核销",
            "团购码在哪", "券还能用吗", "有效期到什么时候",
        ],
    },
    "SB-003": {
        "intents": ["QueryRefund", "RefundRequest"],
        "cases": ["IC-010", "AC-004", "AC-005"],
        "expressions": ["退款到哪了", "什么时候到账", "退款进度", "怎么还没退"],
    },
    "SB-004": {
        "intents": ["QueryOrder", "VoucherUnavailable"],
        "cases": ["PC-001"],
        "expressions": ["付了钱没券", "支付成功怎么没订单", "已支付未出单", "钱扣了没券"],
    },
    "SB-005": {
        "intents": ["QueryVoucher", "VoucherUnavailable"],
        "cases": ["PC-004"],
        "expressions": ["券丢了", "找不到券了", "券怎么没了"],
    },
    "SB-006": {
        "intents": ["VoucherUnavailable", "CheckVoucherAvailability"],
        "cases": ["PC-005"],
        "expressions": ["券过期了", "昨天还能用今天不行了", "过期了还能用吗"],
    },
    "SB-007": {
        "intents": ["QueryCoupon"],
        "cases": ["PC-012", "PC-013", "PC-014"],
        "expressions": ["优惠券用不了", "满减不满足", "为什么不能叠加"],
    },
    "SB-008": {
        "intents": ["StoreUnavailable", "VoucherUnavailable"],
        "cases": ["FC-001", "FC-002", "FC-019"],
        "expressions": ["店关门了", "到店发现没开门", "门店倒闭", "提前关门了"],
    },
    "SB-009": {
        "intents": ["MerchantReject", "VoucherUnavailable"],
        "cases": ["FC-006", "FC-007", "CC-007"],
        "expressions": [
            "老板不给用", "商家说不认", "老板说活动结束", "平台券不能用",
            "店员拒绝扫码", "不让核销",
        ],
    },
    "SB-010": {
        "intents": ["ReservationFailure"],
        "cases": ["FC-009", "FC-010"],
        "expressions": ["约不上", "预约失败", "没有时间", "不给预约"],
    },
    "SB-011": {
        "intents": ["ServiceMismatch"],
        "cases": ["FC-011", "CC-001"],
        "expressions": ["实物和宣传不一样", "少给东西", "双人餐变单人餐", "套餐缺菜"],
    },
    "SB-012": {
        "intents": ["ServiceMismatch"],
        "cases": ["FC-016", "CC-005"],
        "expressions": ["强制消费", "必须买别的", "最低消费", "不点酒水不让用"],
    },
    "SB-013": {
        "intents": ["RefundRequest"],
        "cases": ["AC-001", "AC-002"],
        "expressions": ["我要退款", "不想要了", "帮我退掉", "不去了", "临时有事"],
    },
    "SB-014": {
        "intents": ["QueryRefund", "AppealRequest"],
        "cases": ["AC-006", "AC-005"],
        "expressions": ["退款失败了", "退不了", "退款被拒绝"],
    },
    "SB-015": {
        "intents": ["CompensationRequest"],
        "cases": ["AC-007", "AC-008"],
        "expressions": ["申请补偿", "要赔偿", "体验太差了给点补偿"],
    },
    "SB-016": {
        "intents": ["ServiceComplaint"],
        "cases": ["CC-003", "FC-015"],
        "expressions": ["态度太差", "服务员凶", "爱答不理"],
    },
    "SB-017": {
        "intents": ["SafetyComplaint"],
        "cases": ["CC-008"],
        "expressions": ["吃坏肚子", "食品不新鲜", "有异物", "变质了"],
    },
    "SB-018": {
        "intents": ["SafetyComplaint"],
        "cases": ["CC-009"],
        "expressions": ["被骚扰", "被威胁", "被偷拍", "感觉不安全", "遭受歧视"],
    },
}

# 消息关键词 → (intent, case_hint) 快速路由
MESSAGE_CASE_HINTS: list[tuple[tuple[str, ...], str, str]] = [
    (("吃坏", "异物", "变质", "中毒", "不新鲜"), "SafetyComplaint", "CC-008"),
    (("骚扰", "威胁", "偷拍", "不安全", "歧视"), "SafetyComplaint", "CC-009"),
    (("付了钱没", "支付成功没", "扣了钱没"), "QueryOrder", "PC-001"),
    (("重复下单", "买了两次", "两笔订单"), "QueryOrder", "PC-003"),
    (("券丢了", "找不到券"), "QueryVoucher", "PC-004"),
    (("过期", "昨天还能用"), "VoucherUnavailable", "PC-005"),
    (("门店搬", "地址不对", "搬走了"), "StoreUnavailable", "FC-003"),
    (("打不通", "联系不上", "电话没人接"), "StoreUnavailable", "FC-004"),
    (("排队", "等了两小时", "人太多"), "StoreUnavailable", "FC-005"),
    (("约不上", "预约失败"), "ReservationFailure", "FC-009"),
    (("不给预约", "拒绝预约"), "ReservationFailure", "FC-010"),
    (("缺货", "没货", "卖完了"), "ServiceMismatch", "FC-013"),
    (("加价", "多收钱", "临时涨价"), "PriceDispute", "FC-017"),
    (("服务员没来", "没人服务", "缺席"), "ServiceMismatch", "FC-018"),
    (("只用了部分", "没体验完"), "RefundRequest", "AC-003"),
    (("退款失败", "退不了款"), "AppealRequest", "AC-006"),
    (("申诉", "处理不公平"), "AppealRequest", "AC-009"),
    (("虚假宣传", "图片假"), "MerchantComplaint", "CC-002"),
    (("和宣传不符", "货不对板"), "MerchantComplaint", "CC-001"),
    (("恶意", "黑店"), "MerchantComplaint", "CC-013"),
    (("又投诉", "投诉好几次", "没人管"), "AppealRequest", "CC-015"),
    (("老板不给", "扫不出来", "刷不出来", "核销失败"), "VoucherUnavailable", "FC-008"),
]


def storybook_prompt_block() -> str:
    lines = ["Storybook 口语映射（SB-001~018）："]
    for sb_id, data in STORYBOOK.items():
        expr = " / ".join(data["expressions"][:3])
        intents = ", ".join(data["intents"])
        cases = ", ".join(data["cases"])
        lines.append(f"- {sb_id}: 「{expr}…」→ Intent[{intents}] → Case[{cases}]")
    return "\n".join(lines)


def match_storybook_intents(message: str) -> list[str]:
    hits: list[str] = []
    for data in STORYBOOK.values():
        if any(expr in message for expr in data["expressions"]):
            hits.extend(data["intents"])
    return list(dict.fromkeys(hits))


def match_case_hint(message: str) -> tuple[str, str] | None:
    for keywords, intent, case_id in MESSAGE_CASE_HINTS:
        if any(k in message for k in keywords):
            return intent, case_id
    return None

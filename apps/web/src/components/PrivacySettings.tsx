import type { PrivacySettings as Settings } from "../types";

const items: [keyof Settings, string, string][] = [
  ["order_access", "订单数据", "用于查询团购套餐、电影票、预约服务"],
  ["voucher_access", "券包数据", "用于展示券码、核销状态和有效期"],
  ["coupon_access", "优惠券数据", "用于解释不可用原因和可用范围"],
  ["location_access", "定位城市", "用于匹配门店营业时间和适用城市"],
  ["behavior_summary", "行为摘要", "仅上传聚合标签，不上传原始点击记录"],
  ["stream_response", "流式回复", "前端逐字展示模型回复"],
];

export function PrivacySettings({
  settings,
  onToggle,
}: {
  settings: Settings;
  onToggle: (key: keyof Settings) => void;
}) {
  return (
    <div className="flex-1 overflow-y-auto px-4 py-3 bg-slate-50">
      <div className="rounded-2xl bg-white border border-slate-100 divide-y">
        {items.map(([key, title, desc]) => (
          <div key={key} className="p-4 flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold">{title}</div>
              <div className="text-xs text-slate-500 mt-1">{desc}</div>
            </div>
            <button
              type="button"
              onClick={() => onToggle(key)}
              className={`w-11 h-6 rounded-full relative transition shrink-0 ${
                settings[key] ? "bg-indigo-600" : "bg-slate-300"
              }`}
            >
              <span
                className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition ${
                  settings[key] ? "left-[22px]" : "left-0.5"
                }`}
              />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

-- Seed data for Douyin Life Service Assistant

INSERT INTO users (id, display_name, city, membership_level, phone_mask)
VALUES
  ('user_demo', '小林', '北京', '生活服务金卡', '138****2468')
ON CONFLICT (id) DO NOTHING;

INSERT INTO merchant_stores (id, merchant_name, store_name, category, city, address, business_hours, phone, supports_reservation, metadata)
VALUES
  ('store_hotpot_001', '川巷子火锅', '川巷子火锅·望京店', '美食', '北京', '北京市朝阳区望京街 88 号 3 层', '10:30-22:30', '010-88886666', TRUE, '{"parking":"有停车场","scanner_synced":false,"supports_manual_verify":true}'::jsonb),
  ('store_cinema_001', '星河影城', '星河影城·朝阳大悦城店', '电影演出', '北京', '北京市朝阳区朝阳北路 101 号 6 层', '09:30-24:00', '010-66668888', FALSE, '{"parking":"商场停车","scanner_synced":true,"supports_manual_verify":true}'::jsonb),
  ('store_massage_001', '松间里按摩', '松间里按摩·三里屯店', '休闲娱乐', '北京', '北京市朝阳区三里屯路 19 号', '12:00-02:00', '010-77779999', TRUE, '{"parking":"路边停车","scanner_synced":true,"supports_manual_verify":true}'::jsonb)
ON CONFLICT (id) DO NOTHING;

INSERT INTO life_orders (
  id, user_id, store_id, service_type, title, status, paid_amount, original_amount,
  purchase_time, service_time, expire_time, can_refund, can_reschedule, metadata
)
VALUES
  (
    'order_hotpot_8821', 'user_demo', 'store_hotpot_001', '团购套餐',
    '川巷子火锅双人餐', 'unused', 168.00, 238.00,
    NOW() - INTERVAL '2 days', NULL, NOW() + INTERVAL '12 days',
    TRUE, TRUE, '{"people": 2, "includes": ["锅底", "肥牛", "虾滑", "蔬菜拼盘"], "reservation_required": true}'
  ),
  (
    'order_movie_7718', 'user_demo', 'store_cinema_001', '电影票',
    '星河影城 2D 电影票', 'scheduled', 78.00, 96.00,
    NOW() - INTERVAL '1 day', NOW() + INTERVAL '5 hours', NOW() + INTERVAL '5 hours',
    FALSE, TRUE, '{"movie": "流浪地球3", "seat": "6排8座", "show_time": "今晚 20:10"}'
  ),
  (
    'order_massage_6602', 'user_demo', 'store_massage_001', '预约服务',
    '松间里 90 分钟肩颈按摩', 'refunding', 199.00, 298.00,
    NOW() - INTERVAL '5 days', NOW() - INTERVAL '1 day', NOW() + INTERVAL '25 days',
    TRUE, FALSE, '{"appointment": "昨日 19:30", "reason": "商家临时停业"}'
  )
ON CONFLICT (id) DO NOTHING;

INSERT INTO vouchers (id, order_id, user_id, store_id, code, title, status, valid_from, valid_to, usage_rule)
VALUES
  ('voucher_hotpot_8821', 'order_hotpot_8821', 'user_demo', 'store_hotpot_001', 'DY8821-2468', '川巷子火锅双人餐券', 'unused', NOW() - INTERVAL '2 days', NOW() + INTERVAL '12 days', '需提前 2 小时预约，周末可用，不与店内其他优惠同享。'),
  ('voucher_movie_7718', 'order_movie_7718', 'user_demo', 'store_cinema_001', 'DY7718-1357', '星河影城 2D 电影票', 'scheduled', NOW() - INTERVAL '1 day', NOW() + INTERVAL '5 hours', '开场前 30 分钟可改签一次，开场后不可退改。'),
  ('voucher_massage_6602', 'order_massage_6602', 'user_demo', 'store_massage_001', 'DY6602-9988', '松间里肩颈按摩券', 'refund_pending', NOW() - INTERVAL '5 days', NOW() + INTERVAL '25 days', '预约服务需提前 4 小时取消，商家原因可全额退款。')
ON CONFLICT (id) DO NOTHING;

INSERT INTO coupons (id, user_id, title, discount_amount, threshold_amount, applicable_category, applicable_store_id, status, valid_to, rule_text)
VALUES
  ('coupon_food_20', 'user_demo', '美食满 120 减 20', 20.00, 120.00, '美食', NULL, 'available', NOW() + INTERVAL '3 days', '仅限美食类目，实付满 120 元可用，不与团购套餐叠加。'),
  ('coupon_movie_15', 'user_demo', '电影票满 80 减 15', 15.00, 80.00, '电影演出', NULL, 'unavailable', NOW() + INTERVAL '5 days', '订单实付需满 80 元，当前电影票订单实付 78 元，不满足门槛。')
ON CONFLICT (id) DO NOTHING;

INSERT INTO refund_cases (id, order_id, user_id, reason, status, refundable_amount, estimated_finish_time)
VALUES
  ('refund_6602', 'order_massage_6602', 'user_demo', '商家临时停业导致未服务', 'processing', 199.00, NOW() + INTERVAL '1 day')
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_articles (id, category, title, content, keywords)
VALUES
  (1, 'voucher', '团购券在哪里查看', '用户可在订单详情页查看券码、有效期和适用门店。未使用券可展示给商家核销。', ARRAY['券码','团购券','核销','查看']),
  (2, 'refund', '生活服务退款规则', '未使用且未过期的团购套餐通常支持退款；电影票开场后不可退改；商家原因导致无法履约可申请全额退款。', ARRAY['退款','售后','退票','退改']),
  (3, 'coupon', '优惠券不可用原因', '优惠券不可用通常因为类目不匹配、未达到实付门槛、已过期、或不支持与团购套餐叠加。', ARRAY['优惠券','不能用','门槛','叠加']),
  (4, 'store', '门店预约与营业时间', '部分套餐需要提前预约，可根据门店营业时间和订单规则判断是否支持改约。', ARRAY['预约','营业时间','门店','改约']),
  (5, 'human', '转人工场景', '当涉及投诉、复杂退款、商家纠纷或用户明确要求人工时，应创建服务工单并同步上下文。', ARRAY['人工','投诉','客服','工单'])
ON CONFLICT (id) DO NOTHING;

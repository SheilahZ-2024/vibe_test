-- SDS v1 Storybook 演示场景补充（04）
-- 覆盖：商家拒核销、门店停业、券过期、已支付未出单 等 Case

INSERT INTO users (id, display_name, city, membership_level, phone_mask)
VALUES
  ('user_story_a', '小王', '北京', '普通会员', '139****1001'),
  ('user_story_b', 'Lily', '上海', 'VIP', '137****1002')
ON CONFLICT (id) DO NOTHING;

INSERT INTO merchant_stores (id, merchant_name, store_name, category, city, address, business_hours, phone, supports_reservation, metadata)
VALUES
  ('store_closed_001', '川巷子火锅', '川巷子火锅·停业测试店', '美食', '北京', '北京市海淀区中关村大街 1 号', '10:30-22:30', '010-11112222', TRUE,
   '{"business_status":"suspended","scanner_synced":true,"supports_manual_verify":true}'::jsonb),
  ('store_reject_001', '老码头烧烤', '老码头烧烤·拒核销店', '美食', '北京', '北京市朝阳区工体北路 8 号', '17:00-02:00', '010-33334444', FALSE,
   '{"business_status":"open","merchant_reject":true,"scanner_synced":true}'::jsonb)
ON CONFLICT (id) DO NOTHING;

INSERT INTO life_orders (id, user_id, store_id, service_type, title, status, paid_amount, original_amount, purchase_time, expire_time, can_refund, can_reschedule, metadata)
VALUES
  ('order_no_voucher_001', 'user_story_a', 'store_hotpot_001', '团购套餐', '已支付未出券测试单', 'paid_pending_voucher', 99.00, 129.00, NOW() - INTERVAL '1 hour', NOW() + INTERVAL '30 days', TRUE, FALSE, '{}'),
  ('order_expired_001', 'user_story_a', 'store_hotpot_001', '团购套餐', '过期券测试单', 'unused', 88.00, 128.00, NOW() - INTERVAL '60 days', NOW() - INTERVAL '1 day', TRUE, FALSE, '{}'),
  ('order_closed_store_001', 'user_story_b', 'store_closed_001', '团购套餐', '停业门店测试单', 'unused', 158.00, 218.00, NOW() - INTERVAL '3 days', NOW() + INTERVAL '20 days', TRUE, TRUE, '{"reservation_required":false}'::jsonb),
  ('order_merchant_reject_001', 'user_story_b', 'store_reject_001', '团购套餐', '商家拒核销测试单', 'unused', 128.00, 188.00, NOW() - INTERVAL '2 days', NOW() + INTERVAL '15 days', TRUE, FALSE, '{}')
ON CONFLICT (id) DO NOTHING;

INSERT INTO vouchers (id, order_id, user_id, store_id, code, title, status, valid_from, valid_to, usage_rule)
VALUES
  ('voucher_expired_001', 'order_expired_001', 'user_story_a', 'store_hotpot_001', 'DY-EXP-001', '过期券测试', 'expired', NOW() - INTERVAL '60 days', NOW() - INTERVAL '1 day', '已过期不可核销'),
  ('voucher_closed_001', 'order_closed_store_001', 'user_story_b', 'store_closed_001', 'DY-CLO-001', '停业门店券', 'unused', NOW() - INTERVAL '3 days', NOW() + INTERVAL '20 days', '门店暂停营业期间不可核销'),
  ('voucher_reject_001', 'order_merchant_reject_001', 'user_story_b', 'store_reject_001', 'DY-REJ-001', '拒核销测试券', 'unused', NOW() - INTERVAL '2 days', NOW() + INTERVAL '15 days', '到店出示券码核销')
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_articles (id, category, title, content, keywords)
VALUES
  (6, 'sds', 'SDS核销失败诊断', '券无法核销须按诊断树依次排除：券存在性、订单有效性、过期、已核销、门店匹配、时段、预约、门店营业、商家拒绝、系统异常。', ARRAY['核销','诊断','SDS','FC-008']),
  (7, 'sds', 'SDS升级策略', 'P0：食品安全、人身安全、已支付未出单；P1：门店闭店、商家拒核销；P2：券过期；P3：信息查询。', ARRAY['升级','P0','P1']),
  (8, 'sds', 'Storybook口语映射', '「老板不给用」「扫不出来」→ VoucherUnavailable，可能 FC-006/FC-008。', ARRAY['Storybook','口语']),
  (9, 'fc', '商家拒绝核销 FC-006', '商家无正当理由拒绝核销应联系商家、投诉或转人工。', ARRAY['FC-006','商家']),
  (10, 'fc', '门店暂停营业 FC-001', '门店暂停营业时建议改约、换店或退款。', ARRAY['FC-001','停业'])
ON CONFLICT (id) DO NOTHING;

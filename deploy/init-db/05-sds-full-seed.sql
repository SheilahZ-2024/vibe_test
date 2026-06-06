-- SDS v1 全量 Storybook 演示场景（05）
-- 覆盖 PC/FC/AC/CC 主要 Case，供诊断树验证

-- 门店：搬迁 / 电话不通 / 超负荷 / 提前关门 / 履约能力不足
INSERT INTO merchant_stores (id, merchant_name, store_name, category, city, address, business_hours, phone, supports_reservation, metadata)
VALUES
  ('store_reloc_001', '悦己SPA', '悦己SPA·搬迁店', '休闲娱乐', '北京', '北京市朝阳区新址路 66 号', '10:00-22:00', '010-55550001', TRUE,
   '{"business_status":"open","relocated":true,"new_address":"北京市朝阳区新址路66号B座","scanner_synced":true}'::jsonb),
  ('store_nophone_001', '花间里美容', '花间里·联系困难店', '丽人', '北京', '北京市海淀区花园路 2 号', '09:00-21:00', '010-55550002', TRUE,
   '{"business_status":"open","phone_unreachable":true,"scanner_synced":true}'::jsonb),
  ('store_busy_001', '热门火锅', '热门火锅·排队店', '美食', '北京', '北京市西城区西单北大街 1 号', '11:00-23:00', '010-55550003', TRUE,
   '{"business_status":"open","over_capacity":true,"scanner_synced":true}'::jsonb),
  ('store_early_001', '早打烊咖啡', '早打烊咖啡馆', '美食', '北京', '北京市东城区南锣鼓巷 8 号', '08:00-18:00', '010-55550004', FALSE,
   '{"business_status":"open","early_closure":true,"scanner_synced":true}'::jsonb),
  ('store_weak_001', '小作坊美甲', '小作坊美甲', '丽人', '北京', '北京市丰台区角门 3 号', '10:00-20:00', '010-55550005', TRUE,
   '{"business_status":"open","insufficient_capacity":true,"scanner_synced":true}'::jsonb)
ON CONFLICT (id) DO NOTHING;

INSERT INTO life_orders (id, user_id, store_id, service_type, title, status, paid_amount, original_amount, purchase_time, expire_time, can_refund, can_reschedule, metadata)
VALUES
  ('order_dup_001', 'user_demo', 'store_hotpot_001', '团购套餐', '重复下单测试', 'paid', 168.00, 168.00, NOW() - INTERVAL '1 hour', NOW() + INTERVAL '10 days', TRUE, FALSE, '{"duplicate_order":true}'::jsonb),
  ('order_partial_001', 'user_demo', 'store_massage_001', '预约服务', '部分履约SPA', 'used', 299.00, 399.00, NOW() - INTERVAL '3 days', NOW() + INTERVAL '20 days', TRUE, FALSE, '{"partial_fulfillment":true,"used_items":["肩颈"],"unused_items":["足疗"]}'::jsonb),
  ('order_reloc_001', 'user_story_a', 'store_reloc_001', '预约服务', 'SPA搬迁测试单', 'unused', 199.00, 299.00, NOW() - INTERVAL '1 day', NOW() + INTERVAL '25 days', TRUE, TRUE, '{}'),
  ('order_nophone_001', 'user_story_a', 'store_nophone_001', '团购套餐', '联系不上商家', 'unused', 88.00, 128.00, NOW() - INTERVAL '2 days', NOW() + INTERVAL '18 days', TRUE, TRUE, '{}'),
  ('order_busy_001', 'user_story_b', 'store_busy_001', '团购套餐', '排队太久测试', 'unused', 128.00, 168.00, NOW() - INTERVAL '1 day', NOW() + INTERVAL '14 days', TRUE, TRUE, '{}'),
  ('order_shrink_001', 'user_story_b', 'store_hotpot_001', '团购套餐', '套餐缩水测试', 'used', 168.00, 238.00, NOW() - INTERVAL '1 day', NOW() + INTERVAL '30 days', FALSE, FALSE, '{"service_mismatch":true}'::jsonb),
  ('order_markup_001', 'user_demo', 'store_reject_001', '团购套餐', '临时加价测试', 'unused', 99.00, 99.00, NOW() - INTERVAL '1 day', NOW() + INTERVAL '12 days', TRUE, FALSE, '{"price_dispute":true}'::jsonb),
  ('order_refund_fail_001', 'user_demo', 'store_cinema_001', '电影票', '退款失败测试', 'refunding', 78.00, 96.00, NOW() - INTERVAL '5 days', NOW() + INTERVAL '1 day', FALSE, FALSE, '{}')
ON CONFLICT (id) DO NOTHING;

INSERT INTO vouchers (id, order_id, user_id, store_id, code, title, status, valid_from, valid_to, usage_rule)
VALUES
  ('voucher_dup_001', 'order_dup_001', 'user_demo', 'store_hotpot_001', 'DY-DUP-001', '重复下单券', 'unused', NOW() - INTERVAL '1 hour', NOW() + INTERVAL '10 days', '正常券'),
  ('voucher_reloc_001', 'order_reloc_001', 'user_story_a', 'store_reloc_001', 'DY-REL-001', '搬迁门店券', 'unused', NOW() - INTERVAL '1 day', NOW() + INTERVAL '25 days', '请前往新地址'),
  ('voucher_shrink_001', 'order_shrink_001', 'user_story_b', 'store_hotpot_001', 'DY-SHK-001', '缩水套餐券', 'used', NOW() - INTERVAL '1 day', NOW() + INTERVAL '30 days', '已部分消费')
ON CONFLICT (id) DO NOTHING;

INSERT INTO refund_cases (id, order_id, user_id, reason, status, refundable_amount, estimated_finish_time)
VALUES
  ('refund_fail_001', 'order_refund_fail_001', 'user_demo', '用户申请退款', 'failed', 78.00, NULL),
  ('refund_timeout_001', 'order_massage_6602', 'user_demo', '商家停业', 'timeout', 199.00, NOW() - INTERVAL '2 days')
ON CONFLICT (id) DO NOTHING;

INSERT INTO service_tickets (id, session_id, user_id, order_id, type, status, priority, payload)
VALUES
  ('CMP-DEMO-001', 'sess_demo', 'user_demo', 'order_shrink_001', 'complaint', 'open', 'high', '{"complaint_type":"service_mismatch","case_id":"FC-011"}'::jsonb),
  ('LS-COMP-001', 'sess_demo', 'user_demo', 'order_partial_001', 'compensation_review', 'open', 'normal', '{"status":"pending_review","case_id":"AC-007"}'::jsonb)
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_articles (id, category, title, content, keywords)
VALUES
  (11, 'sds', 'FC全系列升级策略', 'FC-011/016/012为P0；FC-001/002/006/007为P1；FC-008/009为P2。必须先诊断再处置。', ARRAY['FC','履约','升级']),
  (12, 'sds', 'AC售后诊断树', '退款须验证：订单存在→已支付→履约状态→规则→历史退款。', ARRAY['AC','退款','售后']),
  (13, 'sds', 'CC投诉处理原则', '食品安全/人身安全/重复投诉必须P0升级人工。', ARRAY['CC','投诉','P0']),
  (14, 'sds', 'IC查询类处理', 'IC类Case仅Explain+Query，不执行写操作除非用户确认。', ARRAY['IC','查询']),
  (15, 'sds', 'PC平台异常处理', 'PC-001已支付未出单为P0，必须建单+转人工。', ARRAY['PC','平台异常'])
ON CONFLICT (id) DO NOTHING;

-- Douyin Life Service Assistant schema

CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    display_name VARCHAR(64) NOT NULL,
    city VARCHAR(32) NOT NULL,
    membership_level VARCHAR(32) NOT NULL DEFAULT '普通用户',
    phone_mask VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS merchant_stores (
    id VARCHAR(64) PRIMARY KEY,
    merchant_name VARCHAR(128) NOT NULL,
    store_name VARCHAR(128) NOT NULL,
    category VARCHAR(64) NOT NULL,
    city VARCHAR(32) NOT NULL,
    address TEXT NOT NULL,
    business_hours VARCHAR(128) NOT NULL,
    phone VARCHAR(32),
    supports_reservation BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS life_orders (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    store_id VARCHAR(64) NOT NULL REFERENCES merchant_stores(id),
    service_type VARCHAR(64) NOT NULL,
    title VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    paid_amount NUMERIC(10, 2) NOT NULL,
    original_amount NUMERIC(10, 2) NOT NULL,
    purchase_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    service_time TIMESTAMPTZ,
    expire_time TIMESTAMPTZ,
    can_refund BOOLEAN NOT NULL DEFAULT TRUE,
    can_reschedule BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_life_orders_user ON life_orders(user_id);
CREATE INDEX IF NOT EXISTS idx_life_orders_status ON life_orders(status);

CREATE TABLE IF NOT EXISTS vouchers (
    id VARCHAR(64) PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL REFERENCES life_orders(id),
    user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    store_id VARCHAR(64) NOT NULL REFERENCES merchant_stores(id),
    code VARCHAR(64) NOT NULL,
    title VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NOT NULL,
    usage_rule TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vouchers_user ON vouchers(user_id);
CREATE INDEX IF NOT EXISTS idx_vouchers_order ON vouchers(order_id);

CREATE TABLE IF NOT EXISTS coupons (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    title VARCHAR(128) NOT NULL,
    discount_amount NUMERIC(10, 2) NOT NULL,
    threshold_amount NUMERIC(10, 2) NOT NULL DEFAULT 0,
    applicable_category VARCHAR(64),
    applicable_store_id VARCHAR(64) REFERENCES merchant_stores(id),
    status VARCHAR(32) NOT NULL,
    valid_to TIMESTAMPTZ NOT NULL,
    rule_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coupons_user ON coupons(user_id);

CREATE TABLE IF NOT EXISTS refund_cases (
    id VARCHAR(64) PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL REFERENCES life_orders(id),
    user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    reason TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    refundable_amount NUMERIC(10, 2) NOT NULL,
    estimated_finish_time TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_refund_cases_user ON refund_cases(user_id);
CREATE INDEX IF NOT EXISTS idx_refund_cases_order ON refund_cases(order_id);

CREATE TABLE IF NOT EXISTS knowledge_articles (
    id SERIAL PRIMARY KEY,
    category VARCHAR(64) NOT NULL,
    title VARCHAR(128) NOT NULL,
    content TEXT NOT NULL,
    keywords TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS service_tickets (
    id VARCHAR(64) PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    order_id VARCHAR(64) REFERENCES life_orders(id),
    type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'open',
    priority VARCHAR(16) NOT NULL DEFAULT 'normal',
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_service_tickets_session ON service_tickets(session_id);
CREATE INDEX IF NOT EXISTS idx_service_tickets_user ON service_tickets(user_id);

CREATE TABLE IF NOT EXISTS conversation_events (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    intent VARCHAR(64),
    tool_calls JSONB NOT NULL DEFAULT '[]',
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversation_events_session ON conversation_events(session_id);

CREATE TABLE IF NOT EXISTS fulfillment_events (
    id BIGSERIAL PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL REFERENCES life_orders(id),
    user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    store_id VARCHAR(64) NOT NULL REFERENCES merchant_stores(id),
    event_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fulfillment_events_user ON fulfillment_events(user_id);
CREATE INDEX IF NOT EXISTS idx_fulfillment_events_order ON fulfillment_events(order_id);

CREATE TABLE IF NOT EXISTS agent_operation_logs (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64),
    user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    operation_type VARCHAR(64) NOT NULL,
    actor VARCHAR(16) NOT NULL,
    summary TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_operation_logs_user ON agent_operation_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_operation_logs_session ON agent_operation_logs(session_id);

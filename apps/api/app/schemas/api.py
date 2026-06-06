from pydantic import BaseModel, Field


class EdgeContextPacket(BaseModel):
    """App 端侧上报的脱敏生活服务上下文。"""

    user_id: str = "user_demo"
    city: str = "北京"
    recent_order_ids: list[str] = Field(default_factory=list)
    local_voucher_summary: list[str] = Field(default_factory=list)
    behavior_tags: list[str] = Field(default_factory=list)
    location_permission: bool = True
    packet_size_bytes: int = 0


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    edge_context: EdgeContextPacket | None = None
    stream: bool = True


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    intent: str
    pipeline: dict
    service_cards: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    workflow: dict | None = None
    case: dict | None = None


class SessionCreateResponse(BaseModel):
    session_id: str
    user_id: str


class UserServiceContextOut(BaseModel):
    user: dict
    orders: list[dict]
    vouchers: list[dict]
    coupons: list[dict]
    refunds: list[dict]
    stores: list[dict]


class RefundCreate(BaseModel):
    session_id: str
    order_id: str
    reason: str = "用户主动申请退款"


class RefundOut(BaseModel):
    id: str
    order_id: str
    status: str
    refundable_amount: float
    estimated_finish_time: str | None = None


class TicketCreate(BaseModel):
    session_id: str
    order_id: str | None = None
    type: str = "human_handoff"
    payload: dict = Field(default_factory=dict)


class TicketOut(BaseModel):
    id: str
    session_id: str
    type: str
    status: str
    priority: str
    queue_position: int | None = None


class HealthOut(BaseModel):
    status: str
    postgres: str
    redis: str
    llm_mode: str
    llm_ok: bool | None = None
    llm_model: str | None = None


class LLMSettingsOut(BaseModel):
    mode: str
    model: str
    base_url: str
    temperature: float
    top_p: float
    max_tokens: int
    timeout_seconds: float
    fallback_to_mock: bool


class WorkflowActionRequest(BaseModel):
    session_id: str
    action_id: str
    order_id: str | None = None
    voucher_id: str | None = None
    payload: dict = Field(default_factory=dict)

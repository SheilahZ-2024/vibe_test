export interface UserListItem {
  id: string;
  display_name: string;
  city: string;
  membership_level: string;
  phone_mask?: string | null;
  order_count: number;
  voucher_count: number;
  highlight_order?: string | null;
}

export interface EdgeContext {
  user_id: string;
  focus_order_id?: string | null;
  city: string;
  recent_order_ids: string[];
  local_voucher_summary: string[];
  behavior_tags: string[];
  location_permission: boolean;
  packet_size_bytes: number;
}

export interface PrivacySettings {
  order_access: boolean;
  voucher_access: boolean;
  coupon_access: boolean;
  location_access: boolean;
  behavior_summary: boolean;
  stream_response: boolean;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  intent?: string;
  pipeline?: PipelinePayload;
  service_cards?: ServiceCard[];
  tool_calls?: ToolCall[];
}

export interface PipelineStep {
  name: string;
  status: string;
  detail?: string;
}

export interface PipelinePayload {
  steps?: PipelineStep[];
  model?: { mode?: string; latency_s?: number };
}

export interface ServiceCard {
  type: "order" | "voucher" | "coupon" | "refund";
  title: string;
  status: string;
  payload: Record<string, unknown>;
}

export interface ServiceContext {
  user: Record<string, unknown>;
  orders: Record<string, unknown>[];
  vouchers: Record<string, unknown>[];
  coupons: Record<string, unknown>[];
  refunds: Record<string, unknown>[];
  stores: Record<string, unknown>[];
}

export interface ToolCall {
  name: string;
  result?: unknown;
}

export interface WorkflowSolution {
  action_id: string;
  title: string;
  description?: string;
  tool?: string;
}

export interface PendingWriteAction {
  tool: string;
  action_id: string;
  title: string;
  description: string;
  order_id?: string | null;
  voucher_id?: string | null;
  payload?: Record<string, unknown>;
}

export interface WorkflowDiagnosis {
  intent?: string;
  case_id?: string;
  case_name?: string;
  problem_space?: string;
  user_goal?: string;
  escalation?: string;
  issue?: string;
  root_cause?: string;
  confidence?: string;
  triggered_rules?: string[];
  diagnosis?: Array<{ step?: number; check: string; status: string; detail: string; case_id?: string }>;
  solution?: WorkflowSolution[];
}

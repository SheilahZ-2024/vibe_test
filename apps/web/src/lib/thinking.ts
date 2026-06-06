import type { PipelineStep, WorkflowDiagnosis } from "../types";

const INTENT_PHRASES: Record<string, string> = {
  QueryOrder: "查订单状态",
  QueryVoucher: "查看团购券",
  QueryCoupon: "了解优惠券",
  QueryStore: "确认门店信息",
  QueryReservation: "查看预约情况",
  QueryRefund: "跟进退款进度",
  QueryTicket: "查看处理进度",
  CheckVoucherAvailability: "确认券能不能用",
  CheckRefundEligibility: "判断能否退款",
  VoucherUnavailable: "解决到店核销问题",
  ReservationFailure: "处理预约失败",
  MerchantReject: "处理商家拒绝核销",
  StoreUnavailable: "确认门店是否营业",
  ServiceMismatch: "核实服务与套餐是否一致",
  RefundRequest: "办理退款",
  CompensationRequest: "申请补偿",
  AppealRequest: "跟进申诉",
  MerchantComplaint: "反馈商家问题",
  ServiceComplaint: "反馈服务体验",
  SafetyComplaint: "处理安全相关投诉",
  PriceDispute: "核实价格争议",
  HumanTransfer: "转接人工客服",
  clarify: "先弄清您的具体需求",
  chitchat: "陪您聊聊",
};

const DIAGNOSIS_CHECK_PHRASES: Record<string, string> = {
  Storybook匹配: "根据您的描述对上了常见场景",
  券状态校验: "检查了团购券是否有效、是否在有效期内",
  订单状态: "核对了订单是否已支付、能否使用",
  门店营业状态: "查看了门店是否在营业、能否接待",
  核销设备: "排查了扫码核销是否正常",
  退款规则: "对照了退款和售后规则",
  重复投诉: "注意到您可能多次反馈过类似问题",
  食品安全: "按食品安全类问题优先处理",
};

function humanizeIntent(intent?: string) {
  if (!intent) return "您的履约问题";
  return INTENT_PHRASES[intent] ?? "您的履约问题";
}

function humanizeDiagnosisStep(check: string, detail: string) {
  const prefix = DIAGNOSIS_CHECK_PHRASES[check];
  if (prefix) return detail ? `${prefix}：${sanitizeDetail(detail)}` : prefix;
  return sanitizeDetail(detail || check);
}

function sanitizeDetail(detail: string) {
  return detail
    .replace(/\b(IC|PC|FC|AC|CC)-\d{3}\b/g, "")
    .replace(/\bP[0-3]\b/g, "")
    .replace(/Storybook/gi, "")
    .replace(/\(\s*\)/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function humanizePipelineStep(step: PipelineStep, workflow?: WorkflowDiagnosis | null): string | null {
  const detail = step.detail ?? "";
  switch (step.name) {
    case "intent_detect":
      if (detail.includes("clarify") || detail.includes("需澄清")) {
        return "您说的还比较笼统，我先帮您把问题问清楚";
      }
      if (detail.includes("chitchat")) return "先回应您，再带您回到本次消费履约";
      return `我先理解您想${humanizeIntent(workflow?.intent)}`;
    case "service_context":
      if (detail.includes("skipped")) return null;
      return "正在查看您最近的订单、团购券和门店信息";
    case "knowledge_search":
      if (detail.includes("skipped")) return null;
      return detail.startsWith("0") ? "查阅平台服务说明" : "查阅了相关服务说明和规则";
    case "diagnosis_tree":
      if (detail.includes("skipped")) return null;
      if (workflow?.case_name) {
        return `核对完情况，更像是「${workflow.case_name}」`;
      }
      return "正在逐项核对可能的原因";
    case "case_generate":
      if (detail.includes("skipped")) return null;
      if (workflow?.user_goal) return `接下来帮您${workflow.user_goal}`;
      return "已经整理出可行的处理方式";
    case "tool_action":
      if (detail.includes("skipped") || detail.startsWith("0")) return null;
      return "已调取订单、券码和门店等必要信息";
    case "prompt_build":
      return null;
    case "model_response":
      return "正在组织给您的回复";
    default:
      return null;
  }
}

export interface ThinkingLine {
  id: string;
  text: string;
}

export function buildThinkingLines(
  pipeline: PipelineStep[],
  workflow?: WorkflowDiagnosis | null,
  streaming = false
): ThinkingLine[] {
  const lines: ThinkingLine[] = [];
  let index = 0;

  if (streaming && !pipeline.length) {
    return [{ id: "boot", text: "正在理解您的问题…" }];
  }

  for (const step of pipeline) {
    const text = humanizePipelineStep(step, workflow);
    if (text) {
      lines.push({ id: `${step.name}-${index++}`, text });
    }
  }

  if (workflow?.diagnosis?.length) {
    for (const item of workflow.diagnosis.slice(0, 4)) {
      const text = humanizeDiagnosisStep(item.check, item.detail);
      if (text) lines.push({ id: `dx-${item.step ?? index++}`, text });
    }
  }

  if (streaming && pipeline.some((s) => s.name === "tool_action") && !pipeline.some((s) => s.name === "model_response")) {
    lines.push({ id: "reply-pending", text: "信息齐了，马上回复您" });
  }

  return lines;
}

export function summarizeWorkflow(workflow?: WorkflowDiagnosis | null): string | null {
  if (!workflow?.case_name) return null;
  const urgent =
    workflow.escalation === "P0"
      ? "这类问题我会优先帮您处理"
      : workflow.escalation === "P1"
        ? "我会尽快给您可行方案"
        : null;
  return urgent ? `关于「${workflow.case_name}」，${urgent}` : `关于「${workflow.case_name}」`;
}

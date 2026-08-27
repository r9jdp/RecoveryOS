import caseDetailFixtureJson from "../../../../packages/contracts/fixtures/case-detail.json";
import dashboardFixtureJson from "../../../../packages/contracts/fixtures/dashboard.json";
import type {
  ApprovalItem,
  CaseDetailFixture,
  DashboardFixture,
} from "@/types/recovery";

const rawMerchantDashboard = dashboardFixtureJson as DashboardFixture;
export const merchantDashboard: DashboardFixture = {
  ...rawMerchantDashboard,
  policy_settings: {
    ...rawMerchantDashboard.policy_settings,
    require_approval_actions:
      rawMerchantDashboard.policy_settings.require_approval_actions ?? [],
  },
};
export const merchantCase = caseDetailFixtureJson as CaseDetailFixture;

export function buildApprovalItems(
  dashboard: DashboardFixture,
): ApprovalItem[] {
  return dashboard.cases
    .filter(
      (item) =>
        item.case_outcome === "OPEN" || item.case_outcome === "ESCALATED",
    )
    .map((item) => ({
      amount_at_risk_paise: item.amount_at_risk_paise,
      case_id: item.id,
      customer_display_name: item.customer_display_name,
      deadline:
        item.id === merchantCase.case.id
          ? merchantCase.case.recovery_deadline
          : null,
      evidence_kind: dashboard.evidence_kind,
      payment_surface_type: item.payment_surface_type,
      plan_name: item.plan_name,
      policy_reason:
        "Customer-present authentication requires operator approval",
      provider:
        dashboard.evidence_kind === "RAZORPAY_TEST_VERIFIED"
          ? "RAZORPAY_TEST"
          : "MOCK",
      recommended_action: item.recommended_action,
    }));
}

export const approvalItems: ApprovalItem[] =
  buildApprovalItems(merchantDashboard);

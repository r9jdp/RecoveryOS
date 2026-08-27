import caseDetailFixtureJson from "../../../../packages/contracts/fixtures/case-detail.json";
import dashboardFixtureJson from "../../../../packages/contracts/fixtures/dashboard.json";
import type {
  ApprovalItem,
  CaseDetailFixture,
  DashboardFixture,
} from "@/types/recovery";

export const merchantDashboard = dashboardFixtureJson as DashboardFixture;
export const merchantCase = caseDetailFixtureJson as CaseDetailFixture;

export const approvalItems: ApprovalItem[] = merchantDashboard.cases.map(
  (item) => ({
    amount_at_risk_paise: item.amount_at_risk_paise,
    case_id: item.id,
    customer_display_name: item.customer_display_name,
    deadline: merchantCase.case.recovery_deadline,
    evidence_kind: merchantDashboard.evidence_kind,
    payment_surface_type: item.payment_surface_type,
    plan_name: item.plan_name,
    policy_reason: "Customer-present authentication requires operator approval",
    provider:
      merchantDashboard.evidence_kind === "RAZORPAY_TEST_VERIFIED"
        ? "RAZORPAY_TEST"
        : "MOCK",
    recommended_action: item.recommended_action,
  }),
);

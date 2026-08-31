import { operatorMutationHeaders } from "@/lib/operator-session";
import { requireRecoveryApiOrigin } from "@/lib/runtime-config";

export interface RazorpaySubscriptionSyncInput {
  subscription_id: string;
  customer_external_id: string;
  customer_display_name: string;
  preferred_language: string;
}

export interface RazorpaySubscriptionSyncResult {
  mode: "razorpay_test";
  merchant_id: string;
  customer: {
    id: string;
    external_id: string;
    created: boolean;
  };
  subscription: {
    id: string;
    provider_subscription_id: string;
    provider_plan_id: string;
    plan_name: string;
    amount_paise: number;
    currency: string;
    subscription_state: string;
    authorization_url: string | null;
    created: boolean;
  };
  invoices: Array<{
    id: string;
    provider_invoice_id: string;
    billing_cycle_key: string;
    amount_paise: number;
    amount_paid_paise: number;
    currency: string;
    invoice_state: string;
    payment_url: string | null;
    created: boolean;
  }>;
}

interface ErrorPayload {
  error?: { message?: string };
  detail?: string | Array<{ msg?: string }>;
  message?: string;
}

async function responseError(response: Response): Promise<string> {
  const payload = (await response
    .json()
    .catch(() => null)) as ErrorPayload | null;
  if (payload?.error?.message) return payload.error.message;
  if (payload?.message) return payload.message;
  if (typeof payload?.detail === "string") return payload.detail;
  if (Array.isArray(payload?.detail)) {
    const validationMessage = payload.detail.find((item) => item.msg)?.msg;
    if (validationMessage) return validationMessage;
  }
  return `Razorpay subscription sync failed with status ${response.status}.`;
}

function assertHttpsUrl(
  value: unknown,
  field: string,
): asserts value is string | null {
  if (value === null) return;
  if (typeof value === "string") {
    try {
      if (new URL(value).protocol === "https:") return;
    } catch {
      // The explicit contract error below is safer than rendering an invalid URL.
    }
  }
  throw new Error(
    `Razorpay subscription sync returned an invalid ${field}. No provider link was opened.`,
  );
}

function assertNonEmptyString(
  value: unknown,
  field: string,
): asserts value is string {
  if (typeof value === "string" && value.trim().length > 0) return;
  throw new Error(
    `Razorpay subscription sync returned incomplete provider data (${field}).`,
  );
}

function assertBoolean(
  value: unknown,
  field: string,
): asserts value is boolean {
  if (typeof value === "boolean") return;
  throw new Error(
    `Razorpay subscription sync returned incomplete provider data (${field}).`,
  );
}

function assertPaise(value: unknown, field: string): asserts value is number {
  if (Number.isSafeInteger(value) && Number(value) >= 0) return;
  throw new Error(
    `Razorpay subscription sync returned invalid money data (${field}).`,
  );
}

function validateSyncResult(
  value: unknown,
): asserts value is RazorpaySubscriptionSyncResult {
  if (!value || typeof value !== "object") {
    throw new Error("Razorpay subscription sync returned an empty response.");
  }
  const result = value as Partial<RazorpaySubscriptionSyncResult>;
  if (
    !result.customer ||
    !result.subscription ||
    !Array.isArray(result.invoices)
  ) {
    throw new Error(
      "Razorpay subscription sync did not return customer, subscription, and invoice data.",
    );
  }

  if (result.mode !== "razorpay_test") {
    throw new Error(
      "Razorpay subscription sync did not confirm Razorpay Test mode.",
    );
  }
  assertNonEmptyString(result.merchant_id, "merchant ID");
  assertNonEmptyString(result.customer.id, "customer record ID");
  assertNonEmptyString(result.customer.external_id, "customer external ID");
  assertBoolean(result.customer.created, "customer created state");

  assertNonEmptyString(result.subscription.id, "subscription record ID");
  assertNonEmptyString(
    result.subscription.provider_subscription_id,
    "provider subscription ID",
  );
  assertNonEmptyString(
    result.subscription.provider_plan_id,
    "provider plan ID",
  );
  assertNonEmptyString(result.subscription.plan_name, "provider plan name");
  assertPaise(result.subscription.amount_paise, "subscription amount");
  assertNonEmptyString(result.subscription.currency, "subscription currency");
  assertNonEmptyString(
    result.subscription.subscription_state,
    "subscription state",
  );
  assertBoolean(result.subscription.created, "subscription created state");
  assertHttpsUrl(
    result.subscription.authorization_url,
    "subscription authorization URL",
  );
  result.invoices.forEach((invoice, index) => {
    const label = `invoice ${index + 1}`;
    assertNonEmptyString(invoice.id, `${label} record ID`);
    assertNonEmptyString(
      invoice.provider_invoice_id,
      `${label} provider invoice ID`,
    );
    assertNonEmptyString(invoice.billing_cycle_key, `${label} billing cycle`);
    assertPaise(invoice.amount_paise, `${label} amount`);
    assertPaise(invoice.amount_paid_paise, `${label} paid amount`);
    assertNonEmptyString(invoice.currency, `${label} currency`);
    assertNonEmptyString(invoice.invoice_state, `${label} state`);
    assertBoolean(invoice.created, `${label} created state`);
    assertHttpsUrl(invoice.payment_url, `${label} payment URL`);
  });
}

export async function syncRazorpayTestSubscription(
  input: RazorpaySubscriptionSyncInput,
): Promise<RazorpaySubscriptionSyncResult> {
  const baseUrl = requireRecoveryApiOrigin("Razorpay subscription setup");
  const response = await fetch(
    `${baseUrl}/v1/razorpay/test-onboarding/subscriptions/${encodeURIComponent(input.subscription_id)}/sync`,
    {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...operatorMutationHeaders(),
      },
      body: JSON.stringify({
        customer_external_id: input.customer_external_id,
        customer_display_name: input.customer_display_name,
        preferred_language: input.preferred_language,
      }),
    },
  );
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
  const result: unknown = await response.json();
  validateSyncResult(result);
  return result;
}

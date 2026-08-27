import { CardUpdateCheckout } from "./CardUpdateCheckout";

interface CardUpdatePageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

function first(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

export default async function CardUpdatePage({
  searchParams,
}: CardUpdatePageProps) {
  const params = await searchParams;

  return (
    <CardUpdateCheckout
      caseId={first(params.case_id)}
      keyId={first(params.key_id)}
      subscriptionId={first(params.subscription_id)}
    />
  );
}

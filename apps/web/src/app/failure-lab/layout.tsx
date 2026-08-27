import { MerchantShell } from "@/components/features/merchant";

export default function FailureLabLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <MerchantShell>{children}</MerchantShell>;
}

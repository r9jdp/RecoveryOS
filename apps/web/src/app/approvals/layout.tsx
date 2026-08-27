import { MerchantShell } from "@/components/features/merchant";

export default function ApprovalsLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <MerchantShell>{children}</MerchantShell>;
}

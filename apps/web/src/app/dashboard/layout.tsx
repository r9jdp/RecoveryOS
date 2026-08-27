import { MerchantShell } from "@/components/features/merchant";

export default function DashboardLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <MerchantShell>{children}</MerchantShell>;
}

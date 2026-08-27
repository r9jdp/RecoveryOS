import { MerchantShell } from "@/components/features/merchant";

export default function LabLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <MerchantShell>{children}</MerchantShell>;
}

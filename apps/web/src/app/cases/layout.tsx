import { MerchantShell } from "@/components/features/merchant";

export default function CasesLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <MerchantShell>{children}</MerchantShell>;
}

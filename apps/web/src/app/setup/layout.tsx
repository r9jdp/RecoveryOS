import { MerchantShell } from "@/components/features/merchant";

export default function RazorpaySetupLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <MerchantShell>{children}</MerchantShell>;
}

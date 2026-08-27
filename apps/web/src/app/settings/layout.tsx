import { MerchantShell } from "@/components/features/merchant";

export default function SettingsLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <MerchantShell>{children}</MerchantShell>;
}

import { MerchantShell } from "@/components/features/merchant";

export default function VoiceLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <MerchantShell>{children}</MerchantShell>;
}

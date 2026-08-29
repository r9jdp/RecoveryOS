import type { Metadata } from "next";
import { Geist } from "next/font/google";

import { TooltipProvider } from "@/components/shadcn/tooltip";
import { cn } from "@/lib/utils";
import "@/styles/globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist" });

export const metadata: Metadata = {
  title: "RecoveryOS",
  description: "Auditable recovery orchestration for failed subscriptions",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={cn("dark font-sans", geist.variable)}
      suppressHydrationWarning
    >
      <body>
        <TooltipProvider>{children}</TooltipProvider>
      </body>
    </html>
  );
}

import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Newsreader } from "next/font/google";

import { TooltipProvider } from "@/components/shadcn/tooltip";
import "@/styles/globals.css";

const newsreader = Newsreader({
  display: "swap",
  style: ["normal", "italic"],
  subsets: ["latin"],
  variable: "--font-newsreader",
});

const plexSans = IBM_Plex_Sans({
  display: "swap",
  subsets: ["latin"],
  variable: "--font-plex-sans",
  weight: ["400", "500", "600"],
});

const plexMono = IBM_Plex_Mono({
  display: "swap",
  subsets: ["latin"],
  variable: "--font-plex-mono",
  weight: ["400", "500", "600"],
});

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
      className={`${newsreader.variable} ${plexSans.variable} ${plexMono.variable} font-sans`}
      suppressHydrationWarning
    >
      <body>
        <TooltipProvider>{children}</TooltipProvider>
      </body>
    </html>
  );
}

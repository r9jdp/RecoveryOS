"use client";

import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BarChart3,
  Briefcase,
  CircleDot,
  FlaskConical,
  Mic,
  PlugZap,
  Settings,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";

import { Brand } from "@/components/layout";
import { Avatar, AvatarFallback } from "@/components/shadcn/avatar";
import { Badge } from "@/components/shadcn/badge";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarSeparator,
  SidebarTrigger,
  useSidebar,
} from "@/components/shadcn/sidebar";

import styles from "./merchant-shell.module.css";

interface MerchantShellProps {
  children: ReactNode;
}

interface NavigationItem {
  href: string;
  icon: LucideIcon;
  label: string;
}

const primaryItems: NavigationItem[] = [
  { href: "/dashboard", icon: BarChart3, label: "Control Tower" },
  {
    href: "/dashboard#cases",
    icon: Briefcase,
    label: "Recovery cases",
  },
  { href: "/approvals", icon: ShieldCheck, label: "Approval queue" },
  { href: "/dashboard#audit", icon: Activity, label: "Audit trail" },
  { href: "/lab", icon: FlaskConical, label: "Recovery Lab" },
  { href: "/failure-lab", icon: ShieldAlert, label: "Failure lab" },
  { href: "/voice", icon: Mic, label: "Voice outreach" },
];

const utilityItems: NavigationItem[] = [
  { href: "/setup", icon: PlugZap, label: "Razorpay setup" },
  { href: "/settings", icon: Settings, label: "Policy settings" },
];

function isNavigationItemActive(
  item: NavigationItem,
  pathname: string,
  activeHash: string,
) {
  const [route, hash] = item.href.split("#");
  const itemHash = hash ? `#${hash}` : "";

  if (itemHash) return pathname === route && activeHash === itemHash;
  if (route.startsWith("/cases")) return pathname.startsWith("/cases");

  return (
    pathname === route && !(route === "/dashboard" && activeHash === "#audit")
  );
}

function NavigationMenu({
  items,
  pathname,
  activeHash,
}: {
  items: NavigationItem[];
  pathname: string;
  activeHash: string;
}) {
  const { setOpenMobile } = useSidebar();

  return (
    <SidebarMenu>
      {items.map((item) => {
        const active = isNavigationItemActive(item, pathname, activeHash);
        const itemHash = item.href.includes("#");
        const ItemIcon = item.icon;

        return (
          <SidebarMenuItem key={item.href}>
            <SidebarMenuButton
              render={
                <Link
                  href={item.href}
                  aria-current={
                    active ? (itemHash ? "location" : "page") : undefined
                  }
                  onClick={() => setOpenMobile(false)}
                />
              }
              isActive={active}
              tooltip={item.label}
            >
              <ItemIcon aria-hidden="true" />
              <span>{item.label}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        );
      })}
    </SidebarMenu>
  );
}

function SidebarBrand() {
  const { setOpenMobile } = useSidebar();

  return (
    <Link
      className={styles.brandLink}
      href="/dashboard"
      aria-label="RecoveryOS Control Tower"
      onClick={() => setOpenMobile(false)}
    >
      <Brand className={styles.shellBrand} />
    </Link>
  );
}

function TestEnvironmentBadge() {
  return (
    <Badge variant="info" className="w-fit uppercase tracking-wide">
      <CircleDot data-icon="inline-start" aria-hidden="true" />
      Razorpay Test Mode
    </Badge>
  );
}

function getPageLabel(pathname: string) {
  if (pathname.startsWith("/cases")) return "Case workspace";
  if (pathname === "/approvals") return "Approval queue";
  if (pathname === "/lab") return "Recovery Lab";
  if (pathname === "/failure-lab") return "Failure Injection Lab";
  if (pathname === "/voice") return "Voice outreach";
  if (pathname === "/setup") return "Razorpay setup";
  if (pathname === "/settings") return "Policy settings";
  return "Control Tower";
}

function MerchantWorkspace({ children }: MerchantShellProps) {
  const pathname = usePathname();
  const [activeHash, setActiveHash] = useState("");

  useEffect(() => {
    const syncHash = () => setActiveHash(window.location.hash);
    const syncFrame = window.requestAnimationFrame(syncHash);
    window.addEventListener("hashchange", syncHash);

    return () => {
      window.cancelAnimationFrame(syncFrame);
      window.removeEventListener("hashchange", syncHash);
    };
  }, [pathname]);

  const pageLabel = getPageLabel(pathname);

  return (
    <>
      <a className={styles.skipLink} href="#main-content">
        Skip to main content
      </a>

      <Sidebar collapsible="offcanvas" className="border-sidebar-border">
        <SidebarHeader className="h-16 justify-center border-b border-sidebar-border px-3 py-0">
          <SidebarBrand />
        </SidebarHeader>

        <SidebarContent>
          <SidebarGroup className="px-2 py-3">
            <SidebarGroupLabel>Recovery workspace</SidebarGroupLabel>
            <SidebarGroupContent>
              <NavigationMenu
                items={primaryItems}
                pathname={pathname}
                activeHash={activeHash}
              />
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>

        <SidebarFooter className="gap-3 px-3 py-3">
          <SidebarSeparator className="mx-0" />
          <NavigationMenu
            items={utilityItems}
            pathname={pathname}
            activeHash={activeHash}
          />
          <SidebarSeparator className="mx-0" />
          <TestEnvironmentBadge />
          <p className="m-0 text-xs leading-5 text-muted-foreground">
            Provider actions remain operator-gated and fully auditable.
          </p>
        </SidebarFooter>
      </Sidebar>

      <SidebarInset
        id="main-content"
        className="min-w-0 bg-background text-foreground"
        tabIndex={-1}
      >
        <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center justify-between gap-3 border-b border-border bg-background px-4 md:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <SidebarTrigger aria-label="Toggle navigation" />
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="text-xs font-medium text-muted-foreground">
                Revenue recovery
              </span>
              <p className="m-0 truncate text-sm font-medium text-foreground">
                {pageLabel}
              </p>
            </div>
          </div>

          <div className="flex min-w-0 items-center gap-2">
            <span className="hidden sm:inline-flex">
              <TestEnvironmentBadge />
            </span>
            <Avatar aria-label="Signed in as Demo Operator">
              <AvatarFallback>DO</AvatarFallback>
            </Avatar>
          </div>
        </header>

        <div className="mx-auto w-full max-w-[92rem] p-4 md:p-6">
          {children}
        </div>
      </SidebarInset>
    </>
  );
}

export function MerchantShell({ children }: MerchantShellProps) {
  return (
    <SidebarProvider
      className="bg-background"
      style={{ "--sidebar-width": "15rem" } as CSSProperties}
    >
      <MerchantWorkspace>{children}</MerchantWorkspace>
    </SidebarProvider>
  );
}

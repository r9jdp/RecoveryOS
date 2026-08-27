"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { Brand } from "@/components/layout";
import { Icon, TestModeBadge } from "@/components/ui";

import { DemoGuide } from "./DemoGuide";
import styles from "./merchant.module.css";

interface MerchantShellProps {
  children: React.ReactNode;
}

const items = [
  { href: "/dashboard", icon: "chart" as const, label: "Control Tower" },
  {
    href: "/cases/case_fitbox_aug_2026",
    icon: "case" as const,
    label: "FitBox case",
  },
  { href: "/approvals", icon: "shield" as const, label: "Approval queue" },
  { href: "/dashboard#audit", icon: "activity" as const, label: "Audit trail" },
  { href: "/lab", icon: "lab" as const, label: "Recovery Lab" },
  { href: "/voice", icon: "voice" as const, label: "Voice outreach" },
  { href: "/settings", icon: "settings" as const, label: "Policy settings" },
];

function MerchantNavigation({
  pathname,
  onNavigate,
}: {
  pathname: string;
  onNavigate?: () => void;
}) {
  return (
    <>
      <p className={styles.workspaceLabel}>Recovery workspace</p>
      <nav className={styles.nav} aria-label="Primary navigation">
        {items.map((item) => {
          const route = item.href.split("#")[0];
          const active = route.startsWith("/cases")
            ? pathname.startsWith("/cases")
            : pathname === route && !item.href.includes("#");
          return (
            <Link
              key={item.href}
              className={`${styles.navLink} ${active ? styles.navActive : ""}`}
              href={item.href}
              aria-current={active ? "page" : undefined}
              onClick={onNavigate}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}

export function MerchantShell({ children }: MerchantShellProps) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    if (!mobileOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen]);

  return (
    <>
      <a className={styles.skipLink} href="#main-content">
        Skip to main content
      </a>
      <div className={styles.shell}>
        <aside className={styles.sidebar}>
          <Link
            className={styles.brandLink}
            href="/dashboard"
            aria-label="RecoveryOS Control Tower"
          >
            <Brand />
          </Link>
          <MerchantNavigation pathname={pathname} />
          <div className={styles.sidebarFooter}>
            <TestModeBadge />
            <p className={styles.environmentCopy}>
              FitBox demo workspace · external actions disabled by default.
            </p>
          </div>
        </aside>

        <div className={styles.main}>
          <header className={styles.topbar}>
            <div className={styles.topbarStart}>
              <button
                className={styles.menuButton}
                type="button"
                aria-expanded={mobileOpen}
                aria-controls="mobile-navigation"
                aria-label="Open navigation"
                onClick={() => setMobileOpen(true)}
              >
                <Icon name="menu" />
              </button>
              <p className={styles.breadcrumb}>
                Revenue recovery /{" "}
                {pathname.startsWith("/cases")
                  ? "Case workspace"
                  : pathname === "/approvals"
                    ? "Approval queue"
                    : pathname === "/lab"
                      ? "Recovery Lab"
                      : pathname === "/voice"
                        ? "Voice outreach"
                        : pathname === "/settings"
                          ? "Policy settings"
                          : "Control Tower"}
              </p>
            </div>
            <div className={styles.topbarEnd}>
              <DemoGuide />
              <span className={styles.topbarTestMode}>
                <TestModeBadge />
              </span>
              <span
                className={styles.operator}
                aria-label="Signed in as Demo Operator"
              >
                DO
              </span>
            </div>
          </header>
          <main id="main-content" className={styles.content} tabIndex={-1}>
            {children}
          </main>
        </div>
      </div>

      <div
        className={styles.mobileBackdrop}
        data-open={mobileOpen}
        role="presentation"
        onMouseDown={(event) => {
          if (event.target === event.currentTarget) setMobileOpen(false);
        }}
      >
        <aside
          id="mobile-navigation"
          className={styles.mobileDrawer}
          aria-label="Mobile navigation"
          aria-hidden={!mobileOpen}
        >
          <div className={styles.mobileDrawerHeader}>
            <Brand />
            <button
              className={styles.closeButton}
              type="button"
              aria-label="Close navigation"
              onClick={() => setMobileOpen(false)}
            >
              ×
            </button>
          </div>
          <MerchantNavigation
            pathname={pathname}
            onNavigate={() => setMobileOpen(false)}
          />
        </aside>
      </div>
    </>
  );
}

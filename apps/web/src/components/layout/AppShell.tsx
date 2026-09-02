import type { ReactNode } from "react";

import styles from "../../styles/recovery-ui.module.css";
import { TestModeBadge } from "../ui/Badge";
import { Icon } from "../ui/Icon";
import { Brand } from "./Brand";
import { Navigation } from "./Navigation";
import type { NavigationGroup } from "./Navigation";

export interface AppShellProps {
  children: ReactNode;
  navigation: NavigationGroup[];
  breadcrumb?: ReactNode;
  topbarActions?: ReactNode;
  sidebarFooter?: ReactNode;
  operatorInitials?: string;
}

export function AppShell({
  children,
  navigation,
  breadcrumb = "Revenue recovery / Control Tower",
  topbarActions,
  sidebarFooter,
  operatorInitials = "RK",
}: AppShellProps) {
  return (
    <div className={styles.appShell}>
      <aside className={styles.sidebar}>
        <Brand variant="ledger" />
        <Navigation groups={navigation} />
        <div className={styles.sidebarFooter}>
          {sidebarFooter ?? <TestModeBadge />}
        </div>
      </aside>

      <main className={styles.shellMain}>
        <div className={styles.mobileHeader}>
          <Brand variant="ledger" />
          <button
            className={styles.iconButton}
            type="button"
            aria-label="Open navigation"
          >
            <Icon name="menu" />
          </button>
        </div>
        <header className={styles.topbar}>
          <p className={styles.breadcrumb}>{breadcrumb}</p>
          <div className={styles.topbarActions}>
            {topbarActions ?? <TestModeBadge />}
            <span
              className={styles.avatar}
              aria-label={`Signed in as ${operatorInitials}`}
            >
              {operatorInitials}
            </span>
          </div>
        </header>
        <div className={styles.content}>{children}</div>
      </main>
    </div>
  );
}

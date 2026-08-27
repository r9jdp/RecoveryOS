import type { AnchorHTMLAttributes, ReactNode } from "react";

import styles from "../../styles/recovery-ui.module.css";
import { cx } from "../ui/class-names";

export interface NavigationItem extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "children"> {
  label: string;
  icon?: ReactNode;
  active?: boolean;
}

export interface NavigationGroup {
  label?: string;
  items: NavigationItem[];
}

export interface NavigationProps {
  groups: NavigationGroup[];
  ariaLabel?: string;
}

export function Navigation({ groups, ariaLabel = "Primary navigation" }: NavigationProps) {
  return (
    <nav className={styles.nav} aria-label={ariaLabel}>
      {groups.map((group, groupIndex) => (
        <div key={group.label ?? groupIndex}>
          {group.label && <p className={styles.navLabel}>{group.label}</p>}
          {group.items.map(({ label, icon, active, className, ...linkProps }) => (
            <a
              key={label}
              className={cx(styles.navItem, active && styles.navItemActive, className)}
              aria-current={active ? "page" : undefined}
              {...linkProps}
            >
              {icon && <span className={styles.navIcon}>{icon}</span>}
              <span>{label}</span>
            </a>
          ))}
        </div>
      ))}
    </nav>
  );
}

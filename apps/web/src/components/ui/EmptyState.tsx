import type { HTMLAttributes, ReactNode } from "react";

import styles from "../../styles/recovery-ui.module.css";
import { cx } from "./class-names";

export interface EmptyStateProps extends HTMLAttributes<HTMLDivElement> {
  title: string;
  description: string;
  icon?: ReactNode;
  action?: ReactNode;
}

export function EmptyState({ title, description, icon = "↗", action, className, ...props }: EmptyStateProps) {
  return (
    <div className={cx(styles.emptyState, className)} {...props}>
      <div className={styles.emptyStateInner}>
        <span className={styles.emptyStateIcon} aria-hidden="true">
          {icon}
        </span>
        <h3 className={styles.emptyStateTitle}>{title}</h3>
        <p className={styles.emptyStateDescription}>{description}</p>
        {action}
      </div>
    </div>
  );
}

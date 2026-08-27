import type { HTMLAttributes, ReactNode } from "react";

import styles from "../../styles/recovery-ui.module.css";
import { cx } from "../ui/class-names";

export interface PageHeaderProps extends HTMLAttributes<HTMLElement> {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
  className,
  ...props
}: PageHeaderProps) {
  return (
    <header className={cx(styles.sectionHeader, className)} {...props}>
      <div>
        {eyebrow && <p className={styles.eyebrow}>{eyebrow}</p>}
        <h1 className={styles.pageTitle}>{title}</h1>
        {description && <p className={styles.pageDescription}>{description}</p>}
      </div>
      {action}
    </header>
  );
}

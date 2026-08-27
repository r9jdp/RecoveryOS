import type { HTMLAttributes } from "react";

import styles from "../../styles/recovery-ui.module.css";
import { cx } from "../ui/class-names";

export interface BrandProps extends HTMLAttributes<HTMLDivElement> {
  compact?: boolean;
}

export function Brand({ compact = false, className, ...props }: BrandProps) {
  return (
    <div className={cx(styles.brand, className)} {...props}>
      <span className={styles.brandMark} aria-hidden="true" />
      {!compact && <span className={styles.brandName}>RecoveryOS</span>}
    </div>
  );
}

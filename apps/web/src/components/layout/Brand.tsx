import type { HTMLAttributes } from "react";

import styles from "../../styles/recovery-ui.module.css";
import { cx } from "../ui/class-names";

export interface BrandProps extends HTMLAttributes<HTMLDivElement> {
  compact?: boolean;
  variant?: "default" | "ledger";
}

export function Brand({
  compact = false,
  variant = "default",
  className,
  ...props
}: BrandProps) {
  return (
    <div
      className={cx(
        styles.brand,
        variant === "ledger" && styles.brandLedger,
        className,
      )}
      {...props}
    >
      <span className={styles.brandMark} aria-hidden="true" />
      {!compact && <span className={styles.brandName}>RecoveryOS</span>}
    </div>
  );
}

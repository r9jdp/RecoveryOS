import type { HTMLAttributes, ReactNode } from "react";

import styles from "../../styles/recovery-ui.module.css";
import { cx } from "./class-names";

export type BadgeTone = "neutral" | "info" | "success" | "warning" | "danger";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  showDot?: boolean;
  children: ReactNode;
}

const toneClasses: Record<BadgeTone, string> = {
  neutral: styles.badgeNeutral,
  info: styles.badgeInfo,
  success: styles.badgeSuccess,
  warning: styles.badgeWarning,
  danger: styles.badgeDanger,
};

export function Badge({ tone = "neutral", showDot = false, className, children, ...props }: BadgeProps) {
  return (
    <span className={cx(styles.badge, toneClasses[tone], className)} {...props}>
      {showDot && <span className={styles.badgeDot} aria-hidden="true" />}
      {children}
    </span>
  );
}

export function TestModeBadge({ className, ...props }: Omit<BadgeProps, "tone" | "children">) {
  return (
    <span className={cx(styles.badge, styles.testModeBadge, className)} {...props}>
      <span className={styles.badgeDot} aria-hidden="true" />
      Razorpay Test Mode
    </span>
  );
}

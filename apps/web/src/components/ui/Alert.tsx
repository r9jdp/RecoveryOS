import type { HTMLAttributes, ReactNode } from "react";

import styles from "../../styles/recovery-ui.module.css";
import { cx } from "./class-names";

export type AlertTone = "info" | "success" | "warning" | "danger";

export interface AlertProps extends HTMLAttributes<HTMLDivElement> {
  tone?: AlertTone;
  title: string;
  children?: ReactNode;
}

const toneClasses: Record<AlertTone, string> = {
  info: styles.alertInfo,
  success: styles.alertSuccess,
  warning: styles.alertWarning,
  danger: styles.alertDanger,
};

const toneSymbols: Record<AlertTone, string> = {
  info: "i",
  success: "✓",
  warning: "!",
  danger: "×",
};

export function Alert({
  tone = "info",
  title,
  children,
  className,
  ...props
}: AlertProps) {
  return (
    <div
      className={cx(styles.alert, toneClasses[tone], className)}
      role={tone === "danger" ? "alert" : "status"}
      {...props}
    >
      <span className={styles.alertIcon} aria-hidden="true">
        {toneSymbols[tone]}
      </span>
      <div>
        <p className={styles.alertTitle}>{title}</p>
        {children && <div className={styles.alertDescription}>{children}</div>}
      </div>
    </div>
  );
}

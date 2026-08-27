import type { ButtonHTMLAttributes, ReactNode } from "react";

import styles from "../../styles/recovery-ui.module.css";
import { cx } from "./class-names";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  fullWidth?: boolean;
  loading?: boolean;
  leadingIcon?: ReactNode;
}

const variantClasses: Record<ButtonVariant, string> = {
  primary: styles.buttonPrimary,
  secondary: styles.buttonSecondary,
  ghost: styles.buttonGhost,
  danger: styles.buttonDanger,
};

const sizeClasses: Record<ButtonSize, string | undefined> = {
  sm: styles.buttonSm,
  md: undefined,
  lg: styles.buttonLg,
};

export function Button({
  variant = "primary",
  size = "md",
  fullWidth = false,
  loading = false,
  leadingIcon,
  className,
  children,
  disabled,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(
        styles.button,
        variantClasses[variant],
        sizeClasses[size],
        fullWidth && styles.buttonFull,
        className,
      )}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <span className={styles.buttonSpinner} aria-hidden="true" />
      ) : (
        leadingIcon
      )}
      <span>{children}</span>
    </button>
  );
}

import type { HTMLAttributes, ReactNode } from "react";

import styles from "../../styles/recovery-ui.module.css";
import { cx } from "./class-names";

export interface CardProps extends HTMLAttributes<HTMLElement> {
  interactive?: boolean;
}

export function Card({ interactive = false, className, ...props }: CardProps) {
  return (
    <section
      className={cx(
        styles.card,
        interactive && styles.cardInteractive,
        className,
      )}
      {...props}
    />
  );
}

export interface CardHeaderProps extends Omit<
  HTMLAttributes<HTMLDivElement>,
  "title"
> {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}

export function CardHeader({
  title,
  description,
  action,
  className,
  ...props
}: CardHeaderProps) {
  return (
    <header className={cx(styles.cardHeader, className)} {...props}>
      <div>
        <h3 className={styles.cardTitle}>{title}</h3>
        {description && <p className={styles.cardDescription}>{description}</p>}
      </div>
      {action}
    </header>
  );
}

export function CardBody({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div className={cx(styles.cardBody, className)} {...props} />;
}

export function CardFooter({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <footer className={cx(styles.cardFooter, className)} {...props} />;
}

export interface MetricCardProps extends Omit<CardProps, "children"> {
  label: string;
  value: string;
  delta?: string;
  badge?: ReactNode;
}

export function MetricCard({
  label,
  value,
  delta,
  badge,
  ...props
}: MetricCardProps) {
  return (
    <Card {...props}>
      <CardBody>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: "1rem",
          }}
        >
          <p className={styles.metricLabel}>{label}</p>
          {badge}
        </div>
        <p className={styles.metricValue}>{value}</p>
        {delta && <p className={styles.metricDelta}>{delta}</p>}
      </CardBody>
    </Card>
  );
}

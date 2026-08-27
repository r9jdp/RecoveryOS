import type { HTMLAttributes, ReactNode } from "react";

import styles from "../../styles/recovery-ui.module.css";
import { cx } from "./class-names";

export interface ChartShellProps extends HTMLAttributes<HTMLDivElement> {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
}

export function ChartShell({ title, subtitle, action, children, className, ...props }: ChartShellProps) {
  return (
    <div className={cx(styles.chartShell, className)} {...props}>
      <div className={styles.chartHeader}>
        <div>
          <h3 className={styles.chartTitle}>{title}</h3>
          {subtitle && <p className={styles.chartSubtitle}>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

export interface BarDatum {
  label: string;
  value: number;
}

export interface BarChartProps {
  data: BarDatum[];
  valueLabel: (value: number) => string;
}

export function BarChart({ data, valueLabel }: BarChartProps) {
  const max = Math.max(...data.map((datum) => datum.value), 1);
  const accessibleSummary = data.map((datum) => `${datum.label}: ${valueLabel(datum.value)}`).join(", ");

  return (
    <div className={styles.barChart} role="img" aria-label={accessibleSummary}>
      {data.map((datum) => (
        <div className={styles.barItem} key={datum.label} title={`${datum.label}: ${valueLabel(datum.value)}`}>
          <span className={styles.bar} style={{ height: `${Math.max((datum.value / max) * 100, 2)}%` }} />
          <span className={styles.barLabel}>{datum.label}</span>
        </div>
      ))}
    </div>
  );
}

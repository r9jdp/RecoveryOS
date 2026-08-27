import type { HTMLAttributes, ReactNode } from "react";

import styles from "../../styles/recovery-ui.module.css";
import { cx } from "./class-names";

export type TimelineTone = "info" | "success" | "warning" | "danger" | "neutral";

export interface TimelineItem {
  id: string;
  title: string;
  timestamp: string;
  description?: string;
  tone?: TimelineTone;
  trailing?: ReactNode;
}

export interface TimelineProps extends Omit<HTMLAttributes<HTMLOListElement>, "children"> {
  items: TimelineItem[];
}

const markerClasses: Record<TimelineTone, string | undefined> = {
  info: undefined,
  success: styles.timelineMarkerSuccess,
  warning: styles.timelineMarkerWarning,
  danger: styles.timelineMarkerDanger,
  neutral: styles.timelineMarkerNeutral,
};

export function Timeline({ items, className, ...props }: TimelineProps) {
  return (
    <ol className={cx(styles.timeline, className)} {...props}>
      {items.map((item) => (
        <li key={item.id} className={styles.timelineItem}>
          <span className={cx(styles.timelineMarker, markerClasses[item.tone ?? "info"])} aria-hidden="true" />
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem" }}>
              <p className={styles.timelineTitle}>{item.title}</p>
              {item.trailing}
            </div>
            <p className={styles.timelineMeta}>{item.timestamp}</p>
            {item.description && <p className={styles.timelineDescription}>{item.description}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}

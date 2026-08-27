import type { CSSProperties, HTMLAttributes } from "react";

import styles from "../../styles/recovery-ui.module.css";
import { cx } from "./class-names";

export interface SkeletonProps extends HTMLAttributes<HTMLSpanElement> {
  width?: CSSProperties["width"];
  height?: CSSProperties["height"];
}

export function Skeleton({ width = "100%", height = "1rem", className, style, ...props }: SkeletonProps) {
  return (
    <span
      className={cx(styles.skeleton, className)}
      style={{ width, height, ...style }}
      aria-hidden="true"
      {...props}
    />
  );
}

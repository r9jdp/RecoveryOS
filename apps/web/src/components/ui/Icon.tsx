import type { SVGProps } from "react";

export type IconName =
  | "activity"
  | "case"
  | "chart"
  | "chevron"
  | "lab"
  | "menu"
  | "settings"
  | "shield";

const paths: Record<IconName, string> = {
  activity: "M4 12h3l2-6 4 12 2-6h5",
  case: "M4 7h16v12H4z M9 7V5h6v2 M4 11h16",
  chart: "M5 19V9m7 10V5m7 14v-7",
  chevron: "m9 18 6-6-6-6",
  lab: "M9 3h6m-5 0v6l-5 9a2 2 0 0 0 1.7 3h10.6A2 2 0 0 0 19 18l-5-9V3 M8 15h8",
  menu: "M4 7h16M4 12h16M4 17h16",
  settings:
    "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.1 2.1-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5v.2h-3v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1L6.6 17l.1-.1A1.7 1.7 0 0 0 7 15a1.7 1.7 0 0 0-1.5-1H5v-3h.5A1.7 1.7 0 0 0 7 10a1.7 1.7 0 0 0-.3-1.9L6.6 8l2.1-2.1.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.5v-.2h3v.2a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 8l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.5 1h.5v3h-.5a1.7 1.7 0 0 0-1.5 1z",
  shield: "M12 3 5 6v5c0 4.7 2.9 8 7 10 4.1-2 7-5.3 7-10V6z M9 12l2 2 4-5",
};

export interface IconProps extends SVGProps<SVGSVGElement> {
  name: IconName;
  size?: number;
}

export function Icon({ name, size = 20, ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <path d={paths[name]} />
    </svg>
  );
}

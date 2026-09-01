import type { EvidenceKind } from "@/types/recovery";

const inrWhole = new Intl.NumberFormat("en-IN", {
  currency: "INR",
  maximumFractionDigits: 0,
  minimumFractionDigits: 0,
  style: "currency",
});

export function formatPaise(paise: number): string {
  if (!Number.isSafeInteger(paise)) {
    return "—";
  }

  const sign = paise < 0 ? "-" : "";
  const absolute = Math.abs(paise);
  const wholeRupees = Math.trunc(absolute / 100);
  const remainderPaise = absolute % 100;
  const formattedWhole = inrWhole.format(wholeRupees);

  return remainderPaise === 0
    ? `${sign}${formattedWhole}`
    : `${sign}${formattedWhole}.${String(remainderPaise).padStart(2, "0")}`;
}

export function formatBasisPoints(basisPoints: number): string {
  if (!Number.isSafeInteger(basisPoints)) {
    return "—";
  }

  const whole = Math.trunc(basisPoints / 100);
  const fraction = Math.abs(basisPoints % 100);
  return `${whole}.${String(fraction).padStart(2, "0")}%`;
}

export function formatProbability(probability: number): string {
  return new Intl.NumberFormat("en-IN", {
    maximumFractionDigits: 0,
    style: "percent",
  }).format(probability);
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown time";
  }

  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  }).format(date);
}

export function humanize(value: string): string {
  return value
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function formatEvidenceKind(kind: EvidenceKind): string {
  if (kind === "RAZORPAY_TEST_VERIFIED") return "RAZORPAY TEST VERIFIED";
  if (kind === "SYSTEM_DERIVED") return "RecoveryOS system decision";
  return "Seeded demo data";
}

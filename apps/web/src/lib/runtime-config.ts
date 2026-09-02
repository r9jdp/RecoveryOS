export type DataMode = "live" | "demo";

export function dataMode(): DataMode {
  const configured = process.env.NEXT_PUBLIC_DATA_MODE?.trim().toLowerCase();
  if (!configured || configured === "live") return "live";
  if (configured === "demo") return "demo";
  throw new Error(
    `NEXT_PUBLIC_DATA_MODE must be "live" or "demo"; received "${configured}".`,
  );
}

export function demoDataEnabled(): boolean {
  return dataMode() === "demo";
}

function normalizeOrigin(value: string | undefined): string | null {
  const configured = value?.trim();
  return configured ? configured.replace(/\/$/, "") : null;
}

export function recoveryApiOrigin(): string | null {
  return normalizeOrigin(process.env.NEXT_PUBLIC_API_BASE_URL);
}

export function recoveryLabApiOrigin(): string | null {
  return normalizeOrigin(
    process.env.NEXT_PUBLIC_RECOVERY_API_URL ??
      process.env.NEXT_PUBLIC_API_BASE_URL,
  );
}

export function requireRecoveryApiOrigin(resource: string): string {
  const origin = recoveryApiOrigin();
  if (origin) return origin;
  throw new Error(
    `${resource} requires NEXT_PUBLIC_API_BASE_URL in connected mode. A preview workspace is available only when NEXT_PUBLIC_DATA_MODE=demo.`,
  );
}

"use client";

import { useEffect } from "react";

import { Button, EmptyState } from "@/components/ui";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <EmptyState
      title="The Control Tower hit an unexpected error"
      description="Your data is unchanged. Retry this view or return after the API is healthy."
      action={<Button onClick={reset}>Retry dashboard</Button>}
    />
  );
}

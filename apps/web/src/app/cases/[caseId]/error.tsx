"use client";

import { useEffect } from "react";

import { Button, EmptyState } from "@/components/ui";

export default function CaseError({
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
      title="The case workspace hit an unexpected error"
      description="No recovery command was submitted. Retry to reload the latest case state."
      action={<Button onClick={reset}>Retry case</Button>}
    />
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";

import type { FixtureResult } from "@/types/recovery";

interface RecoveryResource<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
  source: "api" | "mock" | null;
  warning: string | null;
}

export function useRecoveryResource<T>(
  loader: (signal: AbortSignal) => Promise<FixtureResult<T>>,
): RecoveryResource<T> {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<Omit<RecoveryResource<T>, "reload">>({
    data: null,
    error: null,
    loading: true,
    source: null,
    warning: null,
  });

  useEffect(() => {
    const controller = new AbortController();

    loader(controller.signal)
      .then((result) => {
        setState({
          data: result.data,
          error: null,
          loading: false,
          source: result.source,
          warning: result.warning ?? null,
        });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setState({
          data: null,
          error:
            error instanceof Error
              ? error.message
              : "Recovery data could not be loaded.",
          loading: false,
          source: null,
          warning: null,
        });
      });

    return () => controller.abort();
  }, [attempt, loader]);

  const reload = useCallback(() => {
    setState((current) => ({ ...current, error: null, loading: true }));
    setAttempt((current) => current + 1);
  }, []);
  return { ...state, reload };
}

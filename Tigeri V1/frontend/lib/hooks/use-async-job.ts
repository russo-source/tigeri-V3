"use client";

import { useEffect, useRef, useState } from "react";

type AsyncJobState<T> = {
  status: "idle" | "running" | "success" | "error";
  data: T | null;
  error: string | null;
};

type UseAsyncJobOptions<T> = {
  enabled?: boolean;
  intervalMs?: number;
  poller: () => Promise<T>;
  isComplete: (data: T) => boolean;
};

export function useAsyncJob<T>({
  enabled = true,
  intervalMs = 2500,
  poller,
  isComplete,
}: UseAsyncJobOptions<T>) {
  const [state, setState] = useState<AsyncJobState<T>>({
    status: enabled ? "running" : "idle",
    data: null,
    error: null,
  });
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!enabled) {
      const resetTimer = setTimeout(() => {
        if (mountedRef.current) {
          setState({ status: "idle", data: null, error: null });
        }
      }, 0);

      return () => {
        clearTimeout(resetTimer);
      };
    }

    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      try {
        const data = await poller();

        if (!mountedRef.current) {
          return;
        }

        if (isComplete(data)) {
          setState({ status: "success", data, error: null });
          return;
        }

        setState({ status: "running", data, error: null });
        timer = setTimeout(tick, intervalMs);
      } catch (error) {
        if (!mountedRef.current) {
          return;
        }

        setState({
          status: "error",
          data: null,
          error: error instanceof Error ? error.message : "Failed to fetch status",
        });
      }
    };

    void tick();

    return () => {
      clearTimeout(timer);
    };
  }, [enabled, intervalMs, isComplete, poller]);

  return state;
}

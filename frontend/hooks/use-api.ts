"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";

type State<T> = { data: T | null; loading: boolean; error: string | null };

/**
 * One request, with loading and error state.
 *
 * The `alive` guard is what stops a slow response from a page the user has
 * already navigated away from writing into an unmounted component.
 */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<State<T>>({ data: null, loading: true, error: null });
  const alive = useRef(true);

  const run = useCallback(async () => {
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const data = await fetcher();
      if (alive.current) setState({ data, loading: false, error: null });
      return data;
    } catch (cause) {
      const message = cause instanceof ApiError ? cause.message : "Something went wrong";
      if (alive.current) setState((prev) => ({ data: prev.data, loading: false, error: message }));
      return null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    alive.current = true;
    void run();
    return () => {
      alive.current = false;
    };
  }, [run]);

  return { ...state, refetch: run };
}

/**
 * Poll, but only while the tab is visible.
 *
 * A background tab polling every three seconds burns the user's battery and
 * the server's capacity to render something nobody is looking at.
 */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs = 4000, deps: unknown[] = []) {
  const state = useApi<T>(fetcher, deps);
  const refetch = state.refetch;

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (timer === null) timer = setInterval(() => void refetch(), intervalMs);
    };
    const stop = () => {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };
    const onVisibility = () => (document.visibilityState === "visible" ? start() : stop());

    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [refetch, intervalMs]);

  return state;
}

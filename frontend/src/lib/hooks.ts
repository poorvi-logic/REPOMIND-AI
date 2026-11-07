import { useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "./format";

export interface AsyncState<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  reload: () => void;
  setData: (value: T) => void;
}

export function useAsync<T>(loader: () => Promise<T>, deps: unknown[], enabled = true): AsyncState<T> {
  const [data, setDataState] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(enabled);
  const [version, setVersion] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    loaderRef.current()
      .then((value) => {
        if (active) setDataState(value);
      })
      .catch((caught: unknown) => {
        if (active) setError(errorText(caught));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [...deps, version, enabled]);

  const reload = useCallback(() => setVersion((value) => value + 1), []);
  const setData = useCallback((value: T) => setDataState(value), []);
  return { data, error, loading, reload, setData };
}

const LAST_PROJECT_KEY = "repomind.lastProject";

export function rememberAnalysis(analysisId: string): void {
  try {
    window.localStorage.setItem(LAST_PROJECT_KEY, analysisId);
  } catch {
    return;
  }
}

export function lastAnalysisId(): string | null {
  try {
    return window.localStorage.getItem(LAST_PROJECT_KEY);
  } catch {
    return null;
  }
}

import { useEffect, useState } from 'react';
import { api, getErrorMessage } from '../api/client';
import { usePreferences } from './usePreferences';

// The request key is part of the state: old dataset values can never acquire a new dataset label.
export function useLiveResource<T>(path: string | null, options: { interval?: number; refresh?: number } = {}) {
  const [state, setState] = useState<{ key: string | null; data?: T; error?: string; loading: boolean }>({ key: null, loading: true });
  const { visible } = usePreferences();
  const interval = options.interval ?? 0, refresh = options.refresh ?? 0;
  useEffect(() => {
    const controller = new AbortController(); let busy = false;
    if (!path) { setState({ key: null, loading: false }); return; }
    setState(old => old.key === path ? old : { key: path, loading: true });
    async function fetchData() {
      if (busy || controller.signal.aborted) return;
      busy = true;
      try { const { data } = await api.get<T>(path!, { signal: controller.signal }); if (!controller.signal.aborted) setState({ key: path, data, loading: false }); }
      catch (e) { if (!controller.signal.aborted) setState(old => ({ ...old, key: path, error: getErrorMessage(e), loading: false })); }
      finally { busy = false; }
    }
    void fetchData();
    const timer = interval && visible ? window.setInterval(fetchData, interval) : undefined;
    return () => { controller.abort(); clearInterval(timer); };
  }, [path, interval, refresh, visible]);
  return { data: state.key === path ? state.data : undefined, error: state.key === path ? state.error : undefined, loading: !!path && (state.key !== path || state.loading) };
}

export function useDebouncedValue<T>(value: T, delay = 250) {
  const [settled, setSettled] = useState(value);
  useEffect(() => { const timer = setTimeout(() => setSettled(value), delay); return () => clearTimeout(timer); }, [value, delay]);
  return settled;
}

import { useEffect, useState } from 'react';
import { getEnvelope, getErrorMessage } from './api/client';
import type { Envelope } from './types/api';

export function useApi<T>(path: string, params?: Record<string, string | number | boolean | undefined>) {
  const [state, setState] = useState<{ loading: boolean; envelope?: Envelope<T>; error?: string }>({ loading: true });
  const serializedParams = JSON.stringify(params ?? {});
  useEffect(() => {
    let active = true;
    setState({ loading: true });
    getEnvelope<T>(path, JSON.parse(serializedParams) as Record<string, string | number | boolean | undefined>)
      .then((envelope) => { if (active) setState({ loading: false, envelope }); })
      .catch((error: unknown) => { if (active) setState({ loading: false, error: getErrorMessage(error) }); });
    return () => { active = false; };
  }, [path, serializedParams]);
  return state;
}

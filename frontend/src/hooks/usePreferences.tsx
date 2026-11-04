import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { PropsWithChildren } from 'react';

export interface Preferences { theme: 'light' | 'dark'; motion: boolean; compact: boolean; pollSeconds: number; collapsed: boolean }
const defaults: Preferences = { theme: 'light', motion: true, compact: false, pollSeconds: 10, collapsed: false };
export function readStored<T>(key: string, fallback: T): T { try { const text = localStorage.getItem(key); return text ? JSON.parse(text) as T : fallback; } catch { return fallback; } }
export function writeStored(key: string, value: unknown) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Preferences remain usable in memory when storage is unavailable. */ } }
const Context = createContext({ settings: defaults, update: (_: Partial<Preferences>) => {}, reduced: false, visible: true });

export function PreferencesProvider({ children }: PropsWithChildren) {
  const [settings, setSettings] = useState<Preferences>(() => {
    const saved = readStored<Partial<Preferences> | null>('genescope-ui-preferences', {}) ?? {};
    return { ...defaults, theme: saved.theme === 'dark' ? 'dark' : 'light', motion: typeof saved.motion === 'boolean' ? saved.motion : true, compact: saved.compact === true, collapsed: saved.collapsed === true, pollSeconds: [5, 10, 30].includes(saved.pollSeconds ?? 0) ? saved.pollSeconds! : 10 };
  });
  const [systemReduced, setSystemReduced] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [visible, setVisible] = useState(!document.hidden);
  useEffect(() => {
    const query = matchMedia('(prefers-reduced-motion: reduce)');
    const media = () => setSystemReduced(query.matches), visibility = () => setVisible(!document.hidden);
    query.addEventListener('change', media); document.addEventListener('visibilitychange', visibility);
    return () => { query.removeEventListener('change', media); document.removeEventListener('visibilitychange', visibility); };
  }, []);
  const reduced = systemReduced || !settings.motion;
  useEffect(() => {
    document.body.setAttribute('arco-theme', settings.theme);
    document.documentElement.dataset.theme = settings.theme;
    document.documentElement.dataset.motion = reduced ? 'reduced' : 'full';
    document.documentElement.dataset.visibility = visible ? 'visible' : 'hidden';
    document.documentElement.dataset.density = settings.compact ? 'compact' : 'comfortable';
    writeStored('genescope-ui-preferences', settings);
  }, [settings, reduced, visible]);
  const context = useMemo(() => ({ settings, update: (value: Partial<Preferences>) => setSettings(old => ({ ...old, ...value })), reduced, visible }), [settings, reduced, visible]);
  return <Context.Provider value={context}>{children}</Context.Provider>;
}
export const usePreferences = () => useContext(Context);

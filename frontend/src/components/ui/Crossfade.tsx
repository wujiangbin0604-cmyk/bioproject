import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { usePreferences } from '../../hooks/usePreferences';

/** Fade a displayed panel out before swapping its data; clean up rapid tab changes. */
export function Crossfade({ identity, children }: { identity: string; children: ReactNode }) {
  const lastDisplayed = useRef(children);
  const { reduced, visible } = usePreferences();
  const [shown, setShown] = useState({ identity, phase: 'enter' });
  useEffect(() => {
    if (reduced || !visible) { setShown({ identity, phase: 'steady' }); return; }
    if (shown.identity === identity) { if (shown.phase === 'exit') setShown(old => ({ ...old, phase: 'enter' })); return; }
    setShown(old => ({ ...old, phase: 'exit' }));
    const timer = setTimeout(() => setShown({ identity, phase: 'enter' }), 130);
    return () => clearTimeout(timer);
  }, [identity, reduced, visible, shown.identity]);
  const current = reduced || !visible || shown.identity === identity;
  useEffect(() => { if (current) lastDisplayed.current = children; }, [children, current]);
  return <div className="crossfade-panel" data-phase={reduced ? 'steady' : shown.phase} aria-busy={!current}>
    {current ? children : lastDisplayed.current}
  </div>;
}

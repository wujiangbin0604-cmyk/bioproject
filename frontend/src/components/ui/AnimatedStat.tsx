import { useEffect, useRef, useState } from 'react';
import { usePreferences } from '../../hooks/usePreferences';
import { motionConfig } from '../../animations/motionConfig';
import { GlassCard } from './GlassCard';
import { Icon } from './Icon';
import type { IconName } from './Icon';
import { Link } from 'react-router-dom';

export function AnimatedStat({ label, value, detail, icon, tone = 'blue', index = 0, to }: { label: string; value?: number | null; detail?: string; icon: IconName; tone?: string; index?: number; to?: string }) {
  const { reduced, visible } = usePreferences();
  const [shown, setShown] = useState(value ?? null), previous = useRef(value);
  useEffect(() => {
    if (value == null) { setShown(null); return; }
    const from = previous.current ?? value; previous.current = value;
    if (reduced || !visible || from === value) { setShown(value); return; }
    let frame = 0; const start = performance.now();
    const update = (now: number) => { const p = Math.min(1, (now - start) / motionConfig.number); setShown(Math.round(from + (value - from) * (1 - (1 - p) ** 3))); if (p < 1) frame = requestAnimationFrame(update); };
    frame = requestAnimationFrame(update); return () => cancelAnimationFrame(frame);
  }, [value, reduced, visible]);
  return <GlassCard hover={!!to} delay={index} className={`animated-stat tone-${tone}`}><div className="stat-icon"><Icon name={icon} size={24} /></div><div className="stat-copy"><span>{label}</span><strong aria-label={value == null ? '正在加载' : String(value)}>{shown == null ? '—' : shown.toLocaleString()}</strong><small>{detail}</small></div><div className="stat-orbit" aria-hidden="true" />{to && <Link className="stat-card-link" to={to} aria-label={`查看${label}详情`} />}</GlassCard>;
}

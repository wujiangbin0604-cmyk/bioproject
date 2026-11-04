import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import { usePreferences } from '../../hooks/usePreferences';

export function FloatingParticles() {
  return <div className="floating-particles" aria-hidden="true">{[0, 1, 2, 3, 4].map(i => <i key={i} className={`particle particle-${i}`} />)}</div>;
}

export function AnimatedDNA({ variant = 'hero', className = '' }: {
  variant?: 'hero' | 'sidebar' | 'header'; className?: string;
}) {
  const id = useId().replaceAll(':', ''), ref = useRef<HTMLDivElement>(null);
  const { reduced, visible } = usePreferences();
  const [inView, setInView] = useState(true);
  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting));
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  const geometry = useMemo(() => {
    const points = Array.from({ length: 97 }, (_, i) => ({ x: i * 4.5, phase: i / 96 * Math.PI * 4 }));
    const path = (sign: number, list = points) => list.map((p, i) => `${i ? 'L' : 'M'} ${p.x.toFixed(2)} ${(78 + Math.sin(p.phase) * 43 * sign).toFixed(2)}`).join(' ');
    const fronts = [1, -1].flatMap(sign => Array.from({ length: 8 }, (_, i) => {
      const section = points.slice(i * 12, i * 12 + 13);
      return Math.cos(section[6].phase) * sign > 0 ? { sign, path: path(sign, section), key: `${sign}_${i}` } : null;
    }).filter((item): item is { sign: number; path: string; key: string } => !!item));
    return { a: path(1), b: path(-1), fronts, rungs: points.filter((_, i) => i % 3 === 1) };
  }, []);
  function parallax(event: PointerEvent<HTMLDivElement>) {
    if (reduced || !ref.current || event.pointerType !== 'mouse') return;
    const box = ref.current.getBoundingClientRect();
    ref.current.style.setProperty('--dna-x', `${((event.clientX - box.left) / box.width - .5) * 10}px`);
    ref.current.style.setProperty('--dna-y', `${((event.clientY - box.top) / box.height - .5) * 7}px`);
  }
  return <div ref={ref} className={`animated-dna dna-${variant} ${className}`} data-active={!reduced && visible && inView}
    aria-hidden="true" onPointerMove={parallax} onPointerLeave={() => {
      ref.current?.style.setProperty('--dna-x', '0px'); ref.current?.style.setProperty('--dna-y', '0px');
    }}>
    <FloatingParticles />
    <svg viewBox="-20 0 472 156" fill="none" className="dna-svg">
      <defs>
        <linearGradient id={`${id}a`} x1="0" y1="0" x2="432" y2="130" gradientUnits="userSpaceOnUse">
          <stop stopColor="#669cfc" /><stop offset=".43" stopColor="#3dcfd5" /><stop offset=".75" stopColor="#71d8e9" /><stop offset="1" stopColor="#ab94f6" />
        </linearGradient>
        <linearGradient id={`${id}b`} x1="0" y1="140" x2="432" y2="0" gradientUnits="userSpaceOnUse">
          <stop stopColor="#b4a0f5" /><stop offset=".5" stopColor="#5dbded" /><stop offset="1" stopColor="#6be1c6" />
        </linearGradient>
        <linearGradient id={`${id}rib`} x1="0" y1="0" x2="0" y2="1">
          <stop stopColor="#88b4fc" /><stop offset=".42" stopColor="#e9faff" /><stop offset="1" stopColor="#67d6d1" />
        </linearGradient>
        <filter id={`${id}shadow`} x="-15%" y="-30%" width="130%" height="170%">
          <feDropShadow dx="0" dy="2" stdDeviation="1.2" floodColor="#4c85cb" floodOpacity=".18" />
        </filter>
      </defs>
      <g className="dna-helix" strokeLinecap="round" strokeLinejoin="round">
        <g opacity=".42">
          <path d={geometry.a} stroke={`url(#${id}a)`} strokeWidth="15" opacity=".18" />
          <path d={geometry.b} stroke={`url(#${id}b)`} strokeWidth="15" opacity=".18" />
          <path d={geometry.a} stroke={`url(#${id}a)`} strokeWidth="8" />
          <path d={geometry.b} stroke={`url(#${id}b)`} strokeWidth="8" />
        </g>
        {geometry.rungs.map(p => {
          const y = Math.sin(p.phase) * 43, skew = Math.cos(p.phase) * 5;
          return <g key={p.x} opacity={.52 + Math.abs(Math.sin(p.phase)) * .35}>
            <path d={`M ${p.x - skew} ${78 - y} L ${p.x + skew} ${78 + y}`} stroke={`url(#${id}rib)`} strokeWidth="6.5" />
            <path d={`M ${p.x - skew - 1} ${78 - y} L ${p.x + skew - 1} ${78 + y}`} stroke="white" strokeWidth="1.2" opacity=".65" />
            <circle cx={p.x + skew} cy={78 + y} r="2.5" fill="#e6fffb" />
          </g>;
        })}
        <g filter={`url(#${id}shadow)`}>
          {geometry.fronts.map(p => <g key={p.key}>
            <path d={p.path} stroke={`url(#${id}${p.sign > 0 ? 'a' : 'b'})`} strokeWidth="10" />
            <path d={p.path} stroke="#d5ffff" strokeWidth="5" opacity=".38" />
            <path d={p.path} stroke="white" strokeWidth="1.8" opacity=".85" transform="translate(0 -2)" />
          </g>)}
        </g>
        <path className="dna-flow" d={geometry.a} stroke="white" strokeWidth="2.4" strokeDasharray="7 92" opacity=".5" />
        <path className="dna-flow dna-flow-reverse" d={geometry.b} stroke="#e8ffff" strokeWidth="2" strokeDasharray="5 112" opacity=".6" />
      </g>
    </svg>
  </div>;
}
export const HeaderDNA = () => <AnimatedDNA variant="header" />;
export const SidebarDNA = () => <AnimatedDNA variant="sidebar" />;
export const HeroDNA = () => <AnimatedDNA variant="hero" />;

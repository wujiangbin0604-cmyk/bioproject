import type { CSSProperties } from 'react';
export type IconName = 'home' | 'database' | 'flask' | 'monitor' | 'compare' | 'features' | 'target' | 'history' | 'settings' | 'search' | 'upload' | 'arrow' | 'chevron' | 'check' | 'close' | 'star' | 'download' | 'expand' | 'grid' | 'list' | 'bell' | 'user' | 'menu' | 'collapse' | 'sun' | 'moon' | 'copy' | 'refresh' | 'dna' | 'info';
const paths: Record<IconName, React.ReactNode> = {
  home: <><path d="m3 10 9-7 9 7v10H7V10" /><path d="M10 20v-7h5v7" /></>,
  database: <><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0" /></>,
  flask: <><path d="M9 3h6m-5 0v7L4 19q-1 3 3 3h10q4 0 3-3l-6-9V3M7 16h10" /><path d="m11 13 2 1" /></>,
  monitor: <><path d="M4 4h16v12H4zM9 21h6M12 16v5" /><path d="m7 11 3-3 3 4 4-5" /></>,
  compare: <><path d="M4 20h17M7 16V9m5 7V4m5 12v-5" /><path d="m4 5 3-3 3 3" /></>,
  features: <><circle cx="12" cy="5" r="3" /><circle cx="5" cy="19" r="3" /><circle cx="19" cy="19" r="3" /><path d="m10 8-4 8m8-8 4 8M8 19h8" /></>,
  target: <><circle cx="11" cy="13" r="8" /><circle cx="11" cy="13" r="4" /><path d="m11 13 9-10m-5 0h5v5" /></>,
  history: <><path d="M3 11a9 9 0 1 1 2 8M3 4v7h7" /><path d="M12 7v6l4 2" /></>,
  settings: <><path d="m9 3-1 3-3 1-2 4 2 3 1 4 4 1 2 2 4-2 3-1 1-4 2-3-2-4-4-1-1-3z" /><circle cx="12" cy="12" r="3" /></>,
  search: <><circle cx="10" cy="10" r="6" /><path d="m15 15 6 6" /></>,
  upload: <><path d="M6 18H5a4 4 0 0 1-1-8 7 7 0 0 1 14-1 5 5 0 0 1 1 9h-1M12 22V9m-5 5 5-5 5 5" /></>,
  arrow: <path d="M4 12h16m-6-6 6 6-6 6" />, chevron: <path d="m9 5 7 7-7 7" />,
  check: <path d="m5 12 5 5L20 6" />, close: <path d="m6 6 12 12M18 6 6 18" />,
  star: <path d="m12 2 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1z" />,
  download: <><path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4" /></>,
  expand: <path d="M9 3H3v6m12-6h6v6M3 15v6h6m6 0h6v-6" />,
  grid: <path d="M3 3h7v7H3zm11 0h7v7h-7zM3 14h7v7H3zm11 0h7v7h-7z" />,
  list: <path d="M8 5h13M8 12h13M8 19h13M3 5h.1M3 12h.1M3 19h.1" />,
  bell: <><path d="M5 17h14l-2-3V9a5 5 0 0 0-10 0v5zM10 21h4" /></>,
  user: <><circle cx="12" cy="7" r="4" /><path d="M4 22v-3a8 8 0 0 1 16 0v3" /></>,
  menu: <path d="M3 5h18M3 12h18M3 19h18" />, collapse: <path d="M3 3h18v18H3zM8 3v18m9-13-4 4 4 4" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1" /></>,
  moon: <path d="M20 15A9 9 0 0 1 9 3a9 9 0 1 0 11 12Z" />,
  copy: <><path d="M8 8h13v13H8zM16 8V3H3v13h5" /></>,
  refresh: <><path d="M20 7a9 9 0 1 0 1 9M20 2v6h-6" /></>,
  dna: <><path d="M5 2c0 8 14 12 14 20M19 2c0 8-14 12-14 20M6 5h12M8 9h8M8 15h8M6 19h12" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7h.1" /></>,
};
export function Icon({ name, size = 20, className = '', style }: { name: IconName; size?: number; className?: string; style?: CSSProperties }) {
  return <svg aria-hidden="true" className={`ui-icon ${className}`} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" style={style}>{paths[name]}</svg>;
}

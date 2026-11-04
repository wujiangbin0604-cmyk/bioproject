import type { CSSProperties } from 'react';
export const staggerStyle = (index = 0): CSSProperties => ({ animationDelay: `${Math.min(index, 5) * 45}ms` });

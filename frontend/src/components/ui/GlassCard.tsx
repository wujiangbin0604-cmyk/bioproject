import type { HTMLAttributes, ReactNode } from 'react';
import { staggerStyle } from '../../animations/transitions';
export interface GlassCardProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> { title?: ReactNode; subtitle?: ReactNode; extra?: ReactNode; hover?: boolean; delay?: number; bodyClassName?: string }
export function GlassCard({ children, title, subtitle, extra, hover = false, delay, className = '', bodyClassName = '', ...props }: GlassCardProps) {
  return <section {...props} className={`glass-card ${hover ? 'glass-hover' : ''} ${delay !== undefined ? 'card-enter' : ''} ${className}`} style={{ ...staggerStyle(delay), ...props.style }}>
    {(title || extra) && <header className="glass-card-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{extra}</header>}
    <div className={`glass-card-body ${bodyClassName}`}>{children}</div>
  </section>;
}

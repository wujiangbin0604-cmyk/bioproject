import { Card } from '@arco-design/web-react';
import type { ReactNode } from 'react';

export function MetricCard({ label, value, detail, icon, accent = 'blue' }: {
  label: string; value: string | number; detail?: string; icon?: ReactNode; accent?: 'blue' | 'teal' | 'amber' | 'ink';
}) {
  return <Card className={`metric-card metric-${accent}`} bordered={false}>
    <div className="metric-head"><span>{label}</span>{icon && <span className="metric-icon">{icon}</span>}</div>
    <div className="metric-value">{value}</div>
    {detail && <div className="metric-detail">{detail}</div>}
  </Card>;
}

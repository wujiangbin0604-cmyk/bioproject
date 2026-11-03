import type { EChartsOption } from 'echarts';
import { Card } from '@arco-design/web-react';
import type { ReactNode } from 'react';
import { EChart } from './EChart';
import { RemotePanel } from './RemotePanel';

export function ChartPanel({ title, subtitle, option, loading = false, error, status, empty = false, height = 310, extra }: {
  title: string; subtitle?: string; option: EChartsOption; loading?: boolean; error?: string; status?: 'available' | 'partial' | 'unavailable'; empty?: boolean; height?: number; extra?: ReactNode;
}) {
  return <Card className="panel-card" bordered={false} title={<div><div className="panel-title">{title}</div>{subtitle && <div className="panel-subtitle">{subtitle}</div>}</div>} extra={extra}>
    <RemotePanel loading={loading} error={error} status={status} empty={empty}>
      <EChart option={option} notMerge lazyUpdate style={{ height }} opts={{ renderer: 'canvas' }} />
    </RemotePanel>
  </Card>;
}

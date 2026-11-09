import { Alert, Empty, Spin } from '@arco-design/web-react';
import type { ReactNode } from 'react';
import type { Availability } from '../types/api';

export function RemotePanel({ loading, error, status, empty, children }: {
  loading: boolean; error?: string; status?: Availability; empty?: boolean; children: ReactNode;
}) {
  if (loading) return <div className="remote-state"><Spin tip="正在读取已保存的实验结果…" /></div>;
  if (error) return <Alert type="error" title="读取失败" content={error} />;
  if (status === 'unavailable') return <Alert type="warning" title="当前结果尚未导入" content="导入实验结果后即可查看。" />;
  if (empty) return <div className="remote-state"><Empty description="暂无可展示记录" /></div>;
  return <>{children}</>;
}

export function SourceNote({ source, note }: { source?: string | null; note?: string | null }) {
  return <div className="source-note">{source && <span>来源：{source}</span>}{note && <span>{note}</span>}</div>;
}

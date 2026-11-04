import { useEffect, useRef, useState } from 'react';
import { Button, Input, Space, Switch } from '@arco-design/web-react';
import { useLiveResource } from '../../hooks/useLiveResource';
import { copyText } from '../../utils/platform';
import { Icon } from '../ui/Icon';
import { ErrorState, EmptyState } from '../ui/States';
interface LogRow { at: string; stage: string; status?: string; completed_folds?: number }
export function TrainingLogs({ taskId, active, revision }: { taskId: string; active: boolean; revision?: number }) {
  const [filter, setFilter] = useState(''), [auto, setAuto] = useState(true);
  const ref = useRef<HTMLDivElement>(null);
  const logs = useLiveResource<{ items: LogRow[] }>(`/api/v1/experiments/${taskId}/logs`, { interval: active ? 2500 : 0, refresh: active ? 0 : revision });
  const rows = (logs.data?.items ?? []).filter(row => row.stage.toLowerCase().includes(filter.toLowerCase())).slice(-200);
  useEffect(() => { if (auto && ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [logs.data, auto]);
  return <><div className="logs-toolbar"><Input.Search aria-label="筛选任务日志" value={filter} onChange={setFilter} placeholder="筛选阶段或错误" allowClear size="small" /><Space><span className="small-note">自动滚动</span><Switch aria-label="日志自动滚动" checked={auto} onChange={setAuto} size="small" /><Button size="small" icon={<Icon name="copy" size={14} />} onClick={() => void copyText(rows.map(r => `${r.at} ${r.stage}`).join('\n'))}>复制</Button></Space></div><ErrorState message={logs.error} /><div ref={ref} className="training-logs" role="log" aria-live="off">{rows.length ? rows.map((row, i) => <div className={`log-row ${row.status === 'failed' ? 'log-error' : ''}`} key={`${row.at}_${i}`}><time>{new Date(row.at).toLocaleTimeString('zh-CN', { hour12: false })}</time><span className="log-marker" /><span>{row.stage}</span></div>) : <EmptyState title="暂无匹配日志" description="实际任务事件到达后显示" />}</div><p className="small-note">仅显示最近200条后端阶段事件。</p></>;
}

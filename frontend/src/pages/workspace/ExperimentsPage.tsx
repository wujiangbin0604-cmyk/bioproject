import { useState } from 'react';
import { Button, Input, Select, Space } from '@arco-design/web-react';
import { useNavigate } from 'react-router-dom';
import type { Task } from '../../api/platform';
import { statusNames } from '../../api/platform';
import { useLiveResource, useDebouncedValue } from '../../hooks/useLiveResource';
import { usePreferences } from '../../hooks/usePreferences';
import { datasetNames } from '../../utils/platform';
import { GlassCard } from '../../components/ui/GlassCard';
import { PageTitle } from '../../components/ui/PageTitle';
import { GradientButton } from '../../components/ui/GradientButton';
import { ErrorState } from '../../components/ui/States';
import { Icon } from '../../components/ui/Icon';
import { TaskTable } from '../../components/experiments/TaskTable';
export default function ExperimentsPage() {
  const navigate = useNavigate(), { settings } = usePreferences();
  const [search, setSearch] = useState(''), [dataset, setDataset] = useState(''), [status, setStatus] = useState(''), [selected, setSelected] = useState<string[]>([]), [refresh, setRefresh] = useState(0);
  const query = new URLSearchParams({ search: useDebouncedValue(search), status, dataset_id: dataset });
  const tasks = useLiveResource<{ items: Task[] }>(`/api/v1/experiments?${query}`, { interval: settings.pollSeconds * 1000, refresh });
  return <div className="workspace-page"><PageTitle icon="history" title="实验历史" description="检索可追溯的实验配置、状态与结果，选择完成的实验进行对比。" extra={<GradientButton onClick={() => navigate('/lab')}>创建实验</GradientButton>} /><GlassCard><div className="workspace-toolbar"><Input.Search aria-label="搜索实验历史" placeholder="搜索任务ID、数据集或算法" value={search} onChange={setSearch} allowClear /><Select aria-label="历史数据集筛选" placeholder="全部数据集" allowClear value={dataset || undefined} onChange={v => setDataset(v ?? '')} options={Object.entries(datasetNames).map(([value, label]) => ({ value, label }))} style={{ width: 190 }} /><Select aria-label="历史状态筛选" placeholder="全部状态" allowClear value={status || undefined} onChange={v => setStatus(v ?? '')} options={['queued', 'preparing', 'running', 'completed', 'failed', 'cancelled'].map(value => ({ value, label: statusNames[value] }))} style={{ width: 130 }} /><Button aria-label="刷新实验列表" icon={<Icon name="refresh" size={17} />} onClick={() => setRefresh(v => v + 1)} /></div><div className="history-selection-bar"><span>已选择 <b>{selected.length}</b> 个实验</span><Space><Button size="small" onClick={() => setSelected([])} disabled={!selected.length}>清空选择</Button><GradientButton size="small" disabled={!selected.length || selected.length > 12} onClick={() => navigate(`/comparison?ids=${selected.join(',')}`)}>对比所选实验</GradientButton></Space></div><ErrorState message={tasks.error} /><TaskTable tasks={tasks.data?.items ?? []} selected={selected} onSelection={setSelected} loading={tasks.loading} /></GlassCard></div>;
}

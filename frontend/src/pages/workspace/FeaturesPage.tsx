import { useMemo, useState } from 'react';
import { Button, Select, Table, Tag } from '@arco-design/web-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { Dataset, Results, Task } from '../../api/platform';
import { names, number } from '../../api/platform';
import { useLiveResource } from '../../hooks/useLiveResource';
import { GlassCard } from '../../components/ui/GlassCard';
import { PageTitle } from '../../components/ui/PageTitle';
import { AnimatedStat } from '../../components/ui/AnimatedStat';
import { DatasetPicker } from '../../components/ui/DatasetPicker';
import { ErrorState, EmptyState, LoadingSkeleton } from '../../components/ui/States';
import { Icon } from '../../components/ui/Icon';
import { EChart } from '../../components/EChart';
import { HeatmapExplorer } from '../../components/charts/HeatmapExplorer';
export default function FeaturesPage() {
  const navigate = useNavigate(), [params] = useSearchParams();
  const [dataset, setDataset] = useState(params.get('dataset') ?? 'pancan'), [task, setTask] = useState(params.get('task') ?? ''), [algorithm, setAlgorithm] = useState(''), [other, setOther] = useState('');
  const tasks = useLiveResource<{ items: Task[] }>(`/api/v1/experiments?status=completed&dataset_id=${dataset}`);
  const chosen = task || tasks.data?.items[0]?.task_id;
  const result = useLiveResource<Results>(chosen ? `/api/v1/experiments/${chosen}/results` : null);
  const comparison = useLiveResource<Results>(other ? `/api/v1/experiments/${other}/results` : null);
  const summary = useLiveResource<Dataset>(`/api/v1/datasets/${dataset}/summary`);
  const r = result.data?.dataset_id === dataset ? result.data.results.find(r => r.algorithm === algorithm) ?? result.data.results[0] : undefined;
  const overlap = useMemo(() => { if (!r || comparison.data?.dataset_id !== dataset || !comparison.data.results[0]) return undefined; const a = new Set(r.selection_frequency.map(f => f.feature)), b = new Set(comparison.data.results[0].selection_frequency.map(f => f.feature)); const count = [...a].filter(f => b.has(f)).length; return { count, jaccard: count / new Set([...a, ...b]).size }; }, [r, comparison.data, dataset]);
  return <div className="workspace-page"><PageTitle icon="features" title="特征分析" description="探索特征排名、训练折选择频率与稳定性，保留原始基因或探针ID。" />
    <GlassCard><div className="workspace-toolbar"><DatasetPicker value={dataset} onChange={v => { setDataset(v); setTask(''); setOther(''); }} /><Select aria-label="选择特征实验" value={chosen} placeholder="选择已完成实验" onChange={v => { setTask(v); setOther(''); }} options={(tasks.data?.items ?? []).map(t => ({ value: t.task_id, label: `${names[t.experiment_config.selection]} K=${t.experiment_config.selection === 'none' ? '全部' : t.experiment_config.k} / ${t.task_id.slice(0, 8)}` }))} /><Select aria-label="特征分析模型" value={r?.algorithm} placeholder="选择模型" onChange={setAlgorithm} options={(result.data?.results ?? []).map(r => ({ value: r.algorithm, label: names[r.algorithm] }))} /></div></GlassCard>
    <ErrorState message={tasks.error || result.error || comparison.error} />{result.loading ? <LoadingSkeleton rows={7} /> : !r ? <EmptyState title="尚无特征分析结果" description="选择一个已完成的实验，或创建新的特征选择实验" action={<Button onClick={() => navigate('/lab')}>创建实验</Button>} /> : <><div className="feature-stat-row"><AnimatedStat label="实际入选特征" value={r.n_features} detail={names[result.data?.configuration.selection ?? 'none']} icon="features" tone="blue" /><GlassCard className="feature-score tone-purple"><Icon name="compare" size={24} /><span>CV 平均 Jaccard</span><strong>{number(r.jaccard_mean)}</strong><small>训练折集合两两重合</small></GlassCard><GlassCard className="feature-score tone-mint"><Icon name="target" size={24} /><span>CV Macro-F1</span><strong>{number(r.metrics.macro_f1.mean)}</strong><small>± {number(r.metrics.macro_f1.std)}</small></GlassCard></div><div className="small-note"><Tag color="purple">探索性排名</Tag>最终开发拟合用于排名；频率与Jaccard来自CV训练折。全特征集合的Jaccard为1不代表生物标志物证据。数据版本：{result.data?.dataset_version}</div>
      <div className="feature-analysis-grid"><GlassCard title={<><Icon name="list" /> 特征排名</>} subtitle={result.data?.configuration.selection === 'none' ? '全特征模式显示开发数据方差排序' : `${names[result.data?.configuration.selection ?? 'anova']} · 前500项`}><Table rowKey="feature" size="small" data={r.ranking} pagination={{ pageSize: 10 }} scroll={{ y: 340 }} columns={[{ title: '特征ID', dataIndex: 'feature' }, { title: '评分', dataIndex: 'score', render: v => number(v, 3), sorter: (a, b) => (a.score ?? 0) - (b.score ?? 0) }]} /></GlassCard><GlassCard title={<><Icon name="features" /> CV 入选频率</>}><EChart style={{ height: 360 }} option={{ tooltip: { trigger: 'axis' }, toolbox: { feature: { saveAsImage: { title: '导出频率图', name: 'GeneScope_selection_frequency' } } }, grid: { left: 120, right: 35, top: 20, bottom: 35 }, xAxis: { type: 'value', min: 0, max: 1 }, yAxis: { type: 'category', inverse: true, data: r.selection_frequency.slice(0, 15).map(f => f.feature), axisLabel: { fontSize: 11 } }, series: [{ type: 'bar', data: r.selection_frequency.slice(0, 15).map(f => f.frequency), itemStyle: { color: '#6ccfca', borderRadius: [0, 4, 4, 0] }, barMaxWidth: 15 }] }} /></GlassCard></div>
      <div className="feature-analysis-grid"><GlassCard title="不同方法 / K 的特征重合"><p className="small-note">比较两个实验在CV各训练折中曾入选的特征并集。不是最终单次选择的交集。</p><Select aria-label="选择特征重合实验" placeholder="选择另一个同数据集实验" allowClear value={other || undefined} onChange={v => setOther(v ?? '')} options={(tasks.data?.items ?? []).filter(t => t.task_id !== chosen).map(t => ({ value: t.task_id, label: `${names[t.experiment_config.selection]} K=${t.experiment_config.k} / ${t.task_id.slice(0, 8)}` }))} />{overlap ? <div className="overlap-values"><div><strong>{overlap.count}</strong><span>共同特征</span></div><Icon name="features" size={36} /><div><strong>{number(overlap.jaccard)}</strong><span>集合 Jaccard</span></div></div> : <EmptyState title="选择另一个实验查看重合" />}</GlassCard><GlassCard title="不同 K 的实验表现"><KPerformance tasks={tasks.data?.items ?? []} /></GlassCard></div>
    </>}{summary.loading ? <LoadingSkeleton rows={5} /> : summary.data?.heatmap && <GlassCard title={<><Icon name="grid" /> 表达热图</>} extra={<Tag color="arcoblue">当前数据集 · {summary.data.version}</Tag>}><HeatmapExplorer data={summary.data.heatmap} /></GlassCard>}<ErrorState message={summary.error} /></div>;
}

function KPerformance({ tasks }: { tasks: Task[] }) {
  const ids = tasks.slice(0, 12).map(t => t.task_id).join(',');
  const result = useLiveResource<{ items: Results[] }>(ids ? `/api/v1/comparison?task_ids=${ids}` : null);
  const rows = result.data?.items.flatMap(t => t.results.map(r => ({ key: `${t.task_id}_${r.algorithm}`, method: names[t.configuration.selection], k: t.configuration.selection === 'none' ? '全部' : t.configuration.k, model: names[r.algorithm], score: r.metrics.macro_f1.mean, seed: t.configuration.seed, folds: `${t.configuration.folds}×${t.configuration.repeats}` }))) ?? [];
  return <><p className="small-note">最近12个完成实验；核对种子、折数和数据版本后比较。</p><Table size="small" rowKey="key" data={rows} scroll={{ x: 500 }} pagination={{ pageSize: 4 }} columns={[{ title: '方法 / K', render: (_, r) => `${r.method} / ${r.k}` }, { title: '模型', dataIndex: 'model' }, { title: '种子 / 折×轮', render: (_, r) => `${r.seed} / ${r.folds}` }, { title: 'Macro-F1', dataIndex: 'score', render: v => number(v) }]} /><ErrorState message={result.error} /></>;
}

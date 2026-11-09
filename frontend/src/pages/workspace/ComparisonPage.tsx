import { displaySplitProtocol } from '../../utils/presentation';
import { useMemo, useState } from 'react';
import { Button, Descriptions, Select, Space, Tabs, Tag } from '@arco-design/web-react';
import { useSearchParams } from 'react-router-dom';
import type { EChartsOption } from 'echarts';
import type { Results, Task } from '../../api/platform';
import { names, number } from '../../api/platform';
import { useLiveResource } from '../../hooks/useLiveResource';
import { datasetNames } from '../../utils/platform';
import { GlassCard } from '../../components/ui/GlassCard';
import { PageTitle } from '../../components/ui/PageTitle';
import { ErrorState, EmptyState, LoadingSkeleton } from '../../components/ui/States';
import { Icon } from '../../components/ui/Icon';
import { EChart } from '../../components/EChart';
import { ConfusionMatrix } from '../../components/charts/ConfusionMatrix';
import { ResultSummary } from '../../components/experiments/ResultSummary';

export default function ComparisonPage() {
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState<string[]>(() => params.get('ids')?.split(',').filter(Boolean).slice(0, 12) ?? []);
  const [metric, setMetric] = useState('macro_f1'), [inspected, setInspected] = useState('');
  const tasks = useLiveResource<{ items: Task[] }>('/api/v1/experiments?status=completed');
  const comparisons = useLiveResource<{ items: Results[] }>(selected.length ? `/api/v1/comparison?task_ids=${selected.join(',')}` : null);
  const rows = comparisons.data?.items.flatMap(t => t.results.map(r => ({ ...r, key: `${t.task_id}_${r.algorithm}`, source: t }))) ?? [];
  const current = rows.find(r => r.key === inspected) ?? rows[0];
  const option = useMemo<EChartsOption>(() => ({ tooltip: { trigger: 'axis' }, toolbox: { feature: { saveAsImage: { title: '导出图表', pixelRatio: 2, name: 'GeneScope_model_comparison' } } }, grid: { top: 30, right: 25, left: 55, bottom: rows.length > 6 ? 105 : 85 },
    xAxis: { type: 'category', data: rows.map(r => `${r.source.dataset_id}\n${names[r.algorithm]}\n${r.source.task_id?.slice(0, 6)}`), axisLabel: { fontSize: 11, interval: 0 }, axisTick: { show: false }, axisLine: { lineStyle: { color: '#e2e9f8' } } },
    yAxis: { type: 'value', min: 0, max: metric === 'time' || metric === 'features' ? undefined : 1, splitLine: { lineStyle: { color: '#edf2fb' } }, name: metric === 'time' ? '秒' : metric === 'features' ? '特征数' : '' },
    dataZoom: rows.length > 6 ? [{ type: 'inside' }, { type: 'slider', height: 14, bottom: 4 }] : [],
    series: [{ type: 'bar', name: metric === 'time' ? 'CV耗时' : metric === 'features' ? '实际特征数' : metric, barMaxWidth: 42, itemStyle: { borderRadius: [6, 6, 0, 0] }, data: rows.map((r, i) => ({ value: metric === 'time' ? r.fit_seconds : metric === 'features' ? r.n_features : r.metrics[metric].mean, itemStyle: { color: ['#5598fb', '#a58bf6', '#48cabe', '#72bdf4'][i % 4] } })) }],
  }), [rows, metric]);
  return <div className="workspace-page"><PageTitle icon="compare" title="模型对比" description="在明确的数据集、任务与评价协议下比较真实模型表现。" />
    <GlassCard><div className="comparison-selector"><span><Icon name="flask" size={18} /> 选择实验</span><Select mode="multiple" aria-label="选择对比实验" placeholder="选择已完成的实验，最多12个" maxTagCount={3} value={selected} onChange={v => { const ids = v.slice(0, 12); setSelected(ids); setParams(ids.length ? { ids: ids.join(',') } : {}); }} options={(tasks.data?.items ?? []).map(t => ({ value: t.task_id, label: `${t.dataset_id} / ${names[t.experiment_config.selection]} K=${t.experiment_config.k} / ${t.task_id.slice(0, 8)}` }))} /></div></GlassCard><ErrorState message={comparisons.error || tasks.error} />
    {comparisons.loading ? <LoadingSkeleton rows={7} /> : !rows.length ? <EmptyState title="选择实验，开始模型对比" description="可同时比较不同算法、特征方案和数据集，评价范围会分别标明" /> : <><GlassCard title={<><Icon name="compare" /> CV 指标对比</>}><Tabs type="rounded" size="small" activeTab={metric} onChange={setMetric}>{[['macro_f1', 'Macro-F1'], ['balanced_accuracy', 'Balanced Accuracy'], ['accuracy', 'Accuracy'], ['features', '特征数量'], ['time', 'CV耗时']].map(([key, title]) => <Tabs.TabPane key={key} title={title} />)}</Tabs><div className="content-enter" key={metric}><EChart option={option} style={{ height: 350 }} /></div></GlassCard>
      <div className="workspace-toolbar"><span className="analysis-label">单模型详细评价</span><Select aria-label="选择详细评价模型" value={current?.key} onChange={setInspected} options={rows.map(r => ({ value: r.key, label: `${r.source.dataset_id} / ${names[r.algorithm]} / ${r.source.task_id?.slice(0, 8)}` }))} style={{ flex: 1 }} /></div>{current && <><div className="comparison-detail-grid"><GlassCard title={<><Icon name="grid" /> 混淆矩阵</>} extra={<Tag color="arcoblue">{datasetNames[current.source.dataset_id]}</Tag>}><ConfusionMatrix result={current} /><p className="small-note">各轮交叉验证预测计数汇总。</p></GlassCard><GlassCard title={<><Icon name="features" /> 各类别 F1</>}><EChart style={{ height: 340 }} option={{ tooltip: { trigger: 'axis' }, toolbox: { feature: { saveAsImage: { title: '导出图表', name: 'GeneScope_class_f1' } } }, grid: { top: 30, left: 110, right: 40, bottom: 35 }, xAxis: { type: 'value', min: 0, max: 1 }, yAxis: { type: 'category', data: current.labels }, series: [{ type: 'bar', data: current.labels.map(label => current.per_class[label]?.['f1-score'] ?? null), itemStyle: { color: '#6d91ee', borderRadius: [0, 5, 5, 0] }, barMaxWidth: 24 }] }} /><p className="small-note">CV训练折平均Jaccard：{number(current.jaccard_mean)}。</p></GlassCard></div><GlassCard title="所选模型的评价来源"><Descriptions column={2} data={[{ label: '数据集版本', value: current.source.dataset_version }, { label: '划分摘要', value: <span className="hash-note">{current.source.split_sha256}</span> }, { label: '分类任务', value: current.source.task_definition }, { label: 'CV配置', value: `${current.source.configuration.folds}折 × ${current.source.configuration.repeats}轮 / 种子${current.source.configuration.seed}` }]} /><p className="small-note">{displaySplitProtocol(current.source.split_protocol)}</p></GlassCard></>}
      {comparisons.data?.items.map(output => <GlassCard key={output.task_id} title={<><Icon name="flask" /> {datasetNames[output.dataset_id]} · {output.task_id?.slice(0, 10)}</>}><ResultSummary output={output} /><Space>{output.results.map(r => <Button key={r.algorithm} size="small" onClick={() => setInspected(`${output.task_id}_${r.algorithm}`)}>{names[r.algorithm]} 详细评价</Button>)}</Space></GlassCard>)}</>}
  </div>;
}

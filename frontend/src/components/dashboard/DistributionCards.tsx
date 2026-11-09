import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { EChartsOption } from 'echarts';
import type { Dataset, Task } from '../../api/platform';
import type { DatasetSummary } from '../../types/api';
import { chartColors, classColor, formatCount } from '../../utils/dashboard';
import { EChart } from '../EChart';
import { Icon } from '../ui/Icon';
import { GlassCard } from '../ui/GlassCard';
import { EmptyState, ErrorState, LoadingSkeleton } from '../ui/States';

export function DistributionCard({ dataset, loading, error }: { dataset?: Dataset; loading: boolean; error?: string }) {
  const counts = dataset?.class_counts;
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  const keyFor = (label: string) => `${dataset?.dataset_id}:${label}`;
  const entries = Object.entries(counts ?? {}), total = entries.reduce((sum, [, count]) => sum + count, 0);
  const visibleTotal = entries.reduce((sum, [label, count]) => sum + (hidden[keyFor(label)] ? 0 : count), 0);
  const option = useMemo<EChartsOption>(() => ({
    color: chartColors, tooltip: { trigger: 'item', formatter: '{b}\n{c} 例 · {d}%' },
    legend: { show: false, selected: Object.fromEntries(Object.keys(counts ?? {}).map(label => [label, !hidden[keyFor(label)]])) },
    series: [{ type: 'pie', radius: ['67%', '88%'], center: ['50%', '50%'], label: { show: false },
      itemStyle: { borderWidth: 3, borderColor: '#fff' }, emphasis: { scaleSize: 4 },
      data: Object.entries(counts ?? {}).map(([name, value]) => ({ name, value, itemStyle: { color: classColor(name, Object.keys(counts ?? {})) } })) }],
  }), [counts, hidden, dataset?.dataset_id]);
  return <GlassCard className="dashboard-distribution" title={<><Icon name="grid" /> 类别分布</>} subtitle="Class Distribution" extra={<span className="panel-chip">{dataset?.classes ?? '—'} 类</span>}>
    <ErrorState message={error} />
    {loading ? <LoadingSkeleton rows={4} /> : entries.length ? <div className="class-distribution-body"><div className="distribution-donut"><EChart option={option} style={{ height: 174 }} /><div className="donut-label"><strong>{formatCount(visibleTotal)}</strong><span>{visibleTotal === total ? '纳入样本' : '已选类别样本'}</span></div></div>
      <table className="class-count-table"><thead><tr><th>类别</th><th>样本</th><th>占比</th></tr></thead><tbody>{entries.map(([label, count]) => <tr key={label}><td><button className="class-legend-button" aria-label={`切换类别 ${label}`} aria-pressed={!hidden[keyFor(label)]} onClick={() => setHidden(previous => ({ ...previous, [keyFor(label)]: !previous[keyFor(label)] }))}><span className="class-dot" style={{ background: classColor(label, Object.keys(counts ?? {})) }} />{label}</button></td><td>{formatCount(count)}</td><td>{total ? (count / total * 100).toFixed(1) : '0.0'}%</td></tr>)}</tbody></table></div> : <EmptyState title="暂无类别统计" action={<Link to="/datasets">导入当前数据集</Link>} />}
    <p className="dashboard-footnote">{dataset?.dataset_id === 'pancan' ? '固定开发集的真实类别统计' : '当前数据集纳入样本的实际类别统计'} · 点击类别切换显示</p>
  </GlassCard>;
}

export function SplitDistributionCard({ task, study, loading, error }: { task?: Task; study?: DatasetSummary; loading: boolean; error?: string }) {
  const fold = task?.folds.find(item => item.train_samples != null && item.validation_samples != null);
  const hasStudy = !!study?.split && study.development_class_counts?.length > 0 && study.reserved_class_counts?.length > 0;
  const option = useMemo<EChartsOption>(() => {
    const labels = study?.development_class_counts?.map(item => item.code) ?? [];
    return { color: chartColors, tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { top: 0, left: 0, itemWidth: 8, itemHeight: 8, textStyle: { fontSize: 10 } },
      grid: { top: hasStudy ? 38 : 22, bottom: 25, left: 68, right: 16 },
      xAxis: { type: 'value', min: 0, axisLabel: { fontSize: 10 }, splitLine: { lineStyle: { color: '#edf1f7' } } },
      yAxis: { type: 'category', inverse: true, data: hasStudy ? ['开发集', '保留集'] : ['Train', 'Validation'], axisLine: { show: false }, axisTick: { show: false }, axisLabel: { fontSize: 11 } },
      series: hasStudy ? labels.map(code => ({ name: code, type: 'bar' as const, stack: 'samples', barWidth: 23, itemStyle: { color: classColor(code, labels) }, emphasis: { focus: 'series' as const }, data: [study!.development_class_counts.find(c => c.code === code)?.sample_count ?? 0, study!.reserved_class_counts.find(c => c.code === code)?.sample_count ?? 0] })) : [{ name: '实际样本数', type: 'bar', barWidth: 23, label: { show: true, position: 'insideRight' }, data: [{ value: fold?.train_samples ?? 0, itemStyle: { color: chartColors[0] } }, { value: fold?.validation_samples ?? 0, itemStyle: { color: chartColors[1] } }] }],
    };
  }, [study, fold, hasStudy]);
  return <GlassCard className="dashboard-split" title={<><Icon name="features" /> 数据集划分</>} subtitle="Train / Validation / Test" extra={<span className="panel-chip">{hasStudy ? '固定划分' : task ? `${task.experiment_config.folds}折 CV` : '待实验'}</span>}>
    <ErrorState message={error} />
    {loading ? <LoadingSkeleton rows={4} /> : hasStudy || fold ? <><EChart option={option} style={{ height: 170 }} /><div className="split-summary">{hasStudy ? <><span>开发集 <b>{formatCount(study!.split.development_samples)}</b></span><span>保留集 <b>{formatCount(study!.split.reserved_samples)}</b></span></> : <><span>Train <b>{formatCount(fold?.train_samples)}</b></span><span>Validation <b>{formatCount(fold?.validation_samples)}</b></span></>}</div></> : <EmptyState title="暂无可用划分记录" description="完成实验后展示实际训练与验证样本数" action={<Link to="/lab">创建实验</Link>} />}
    <p className="dashboard-footnote">{hasStudy ? '原研究全队列固定划分。点击图例可切换类别。' : fold ? `最近实验 ${task?.task_id.slice(0, 8)} · 第${fold.repeat}轮第${fold.fold}折。` : '完成实验后展示训练与验证样本分布。'}</p>
  </GlassCard>;
}

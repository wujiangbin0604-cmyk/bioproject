import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { EChartsOption } from 'echarts';
import type { Dataset } from '../../api/platform';
import { names } from '../../api/platform';
import type { OverviewRow } from '../charts/OverviewAnalysisChart';
import { chartColors, classColor } from '../../utils/dashboard';
import { EChart } from '../EChart';
import { HeatmapExplorer } from '../charts/HeatmapExplorer';
import { GlassCard } from '../ui/GlassCard';
import { Icon } from '../ui/Icon';
import { EmptyState, ErrorState, LoadingSkeleton } from '../ui/States';

export function ExplorationCard({ dataset, rows, loading, error }: { dataset?: Dataset; rows: OverviewRow[]; loading: boolean; error?: string }) {
  const [tab, setTab] = useState('counts');
  const option = useMemo<EChartsOption>(() => {
    const entries = Object.entries(dataset?.class_counts ?? {}), features = tab === 'features';
    return { color: chartColors, tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: value => features ? `${(Number(value) * 100).toFixed(2)}%` : `${value} 例` },
      grid: { left: 48, right: 16, top: 24, bottom: features ? 65 : 30 },
      xAxis: { type: 'category', data: features ? rows.map(row => `${names[row.algorithm]}\nK=${row.config.selection === 'none' ? '全部' : row.config.k}\n${row.task?.slice(0, 6)}`) : entries.map(([label]) => label), axisTick: { show: false }, axisLine: { lineStyle: { color: '#dce5f0' } }, axisLabel: { fontSize: 10, interval: 0, lineHeight: 15, width: 90, overflow: 'truncate' } },
      yAxis: { type: 'value', min: 0, max: features ? 1 : undefined, axisLabel: { fontSize: 10, formatter: value => features ? `${Number(value) * 100}%` : String(value) }, splitLine: { lineStyle: { color: '#edf1f7' } } },
      dataZoom: features && rows.length > 5 ? [{ type: 'inside' }, { type: 'slider', height: 10, bottom: 0, end: Math.min(100, 500 / rows.length) }] : [],
      series: [{ name: features ? 'CV Macro-F1' : '样本数', type: 'bar', barMaxWidth: 36, label: { show: !features, position: 'top', color: '#5b6d86', fontSize: 10 }, data: features ? rows.map((row, i) => ({ value: row.metrics.macro_f1?.mean, itemStyle: { color: chartColors[i % chartColors.length], borderRadius: [3, 3, 0, 0] } })) : entries.map(([label, value]) => ({ value, itemStyle: { color: classColor(label, entries.map(([name]) => name)), borderRadius: [3, 3, 0, 0] } })) }],
    };
  }, [dataset, rows, tab]);
  return <GlassCard className="dashboard-exploration" title={<><Icon name="compare" /> 数据与特征探索</>} subtitle="Data & Feature Exploration" extra={<Link to={`/features?dataset=${dataset?.dataset_id ?? ''}`} className="quiet-link">特征分析 <Icon name="chevron" size={12} /></Link>}>
    <div className="dashboard-tabs exploration-tabs" aria-label="探索图表类型">{[['counts', '类别样本数'], ['features', 'Top-K 性能'], ['heatmap', '表达热图']].map(([key, label]) => <button key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>{label}</button>)}</div>
    <ErrorState message={error} />
    {loading ? <LoadingSkeleton rows={5} /> : tab === 'heatmap' ? <HeatmapExplorer data={dataset?.heatmap} compact /> : (tab === 'features' ? rows.length : Object.keys(dataset?.class_counts ?? {}).length) ? <EChart option={option} style={{ height: 224 }} /> : <EmptyState title={tab === 'features' ? '暂无特征选择实验' : '暂无样本统计'} action={<Link to={tab === 'features' ? '/lab' : '/datasets'}>{tab === 'features' ? '创建真实实验' : '导入数据集'}</Link>} />}
    {tab !== 'heatmap' && <p className="dashboard-footnote">{tab === 'features' ? '最近实验的实际 K 与 CV Macro-F1；算法、选择方法及划分可能不同，实验详情可追溯。' : '纵轴从 0 开始；数据来自当前数据集的实际纳入样本。'}</p>}
  </GlassCard>;
}

import { useMemo, useState } from 'react';
import { Button, Tooltip } from '@arco-design/web-react';
import { Link } from 'react-router-dom';
import type { EChartsOption } from 'echarts';
import type { OverviewRow } from '../charts/OverviewAnalysisChart';
import { names } from '../../api/platform';
import { algorithmOrder, chartColors, formatPercent, macroClassMetric } from '../../utils/dashboard';
import { GlassCard } from '../ui/GlassCard';
import { Icon } from '../ui/Icon';
import { ErrorState, LoadingSkeleton } from '../ui/States';
import { EChart } from '../EChart';

function MetricCell({ value, highlight }: { value?: number; highlight?: boolean }) {
  return <td className={highlight ? 'metric-highlight' : ''}><span>{formatPercent(value)}</span><span className="metric-track"><i style={{ width: `${Math.max(0, Math.min(100, (value ?? 0) * 100))}%` }} /></span></td>;
}
export function PerformanceTable({ rows, loading, error, datasetId }: { rows: OverviewRow[]; loading: boolean; error?: string; datasetId: string }) {
  const [mode, setMode] = useState('table');
  const recent = algorithmOrder.map(algorithm => rows.find(row => row.algorithm === algorithm));
  const available = recent.filter((row): row is OverviewRow => !!row);
  const option = useMemo<EChartsOption>(() => ({
    color: chartColors, tooltip: { trigger: 'axis', valueFormatter: value => formatPercent(Number(value)) },
    grid: { left: 122, right: 30, top: 18, bottom: 32 },
    xAxis: { type: 'value', min: 0, max: 1, axisLabel: { formatter: value => `${Number(value) * 100}%` }, splitLine: { lineStyle: { color: '#edf1f7' } } },
    yAxis: { type: 'category', inverse: true, data: available.map(row => names[row.algorithm]), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { fontSize: 11 } },
    series: [{ type: 'bar', name: 'CV Macro-F1', barMaxWidth: 24, data: available.map((row, i) => ({ value: row.metrics.macro_f1?.mean, itemStyle: { color: chartColors[i], borderRadius: [0, 4, 4, 0] } })) }],
  }), [rows]); // Results arrive in newest-task order; keep one recorded run per algorithm.
  return <GlassCard className="dashboard-performance" title={<><Icon name="flask" /> 模型性能对比</>} subtitle="Model Performance Comparison" extra={<div className="dashboard-tabs" aria-label="性能展示方式">{[['table', '指标表'], ['chart', 'Macro-F1']].map(([key, label]) => <button key={key} aria-pressed={mode === key} onClick={() => setMode(key)}>{label}</button>)}</div>}>
    <ErrorState message={error} />
    <div className="performance-scope"><span><i />{datasetId.toUpperCase()} · 最近完成实验</span><Link to="/comparison">完整对比 <Icon name="chevron" size={12} /></Link></div>
    {loading ? <LoadingSkeleton rows={5} /> : mode === 'chart' && available.length ? <EChart option={option} style={{ height: 221 }} /> : <div className="dashboard-table-scroll"><table className="performance-table"><thead><tr><th>模型 / 实验</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>Macro-F1</th></tr></thead><tbody>{algorithmOrder.map((algorithm, index) => {
      const row = recent[index];
      return <tr key={algorithm}><th scope="row"><span className="model-name"><i style={{ background: chartColors[index] }} />{names[algorithm]}</span>{row ? <Tooltip content={`${names[row.config.selection]} / K=${row.config.selection === 'none' ? '全部' : row.config.k} / ${row.config.folds}折 × ${row.config.repeats}轮`}><Link to={`/monitor/${row.task}`}>实验 {row.task?.slice(0, 6)} <Icon name="chevron" size={10} /></Link></Tooltip> : <small>尚无已完成结果</small>}</th><MetricCell value={row?.metrics.accuracy?.mean} /><MetricCell value={macroClassMetric(row, 'precision')} /><MetricCell value={macroClassMetric(row, 'recall')} /><MetricCell value={row?.metrics.macro_f1?.mean} highlight /></tr>;
    })}</tbody></table></div>}
    {!loading && !error && !available.length && <div className="performance-empty"><span>运行真实实验后，此处自动更新指标。</span><Link to={`/lab?dataset=${datasetId}`}><Button type="primary" size="mini">创建实验</Button></Link></div>}
    <p className="dashboard-footnote">Accuracy / Macro-F1 为 CV 折均值；Precision / Recall 为 OOF 逐类宏平均。各模型取最近记录，配置可悬停查看。</p>
  </GlassCard>;
}

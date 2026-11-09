import { useMemo, useRef, useState } from 'react';
import { Button, Select, Space, Tooltip } from '@arco-design/web-react';
import type { EChartsOption } from 'echarts';
import type { Dataset } from '../../api/platform';
import { EChart } from '../EChart';
import { Icon } from '../ui/Icon';
import { EmptyState } from '../ui/States';
export function HeatmapExplorer({ data, compact = false }: { data?: Dataset['heatmap']; compact?: boolean }) {
  const [transpose, setTranspose] = useState(false), [features, setFeatures] = useState(compact ? 10 : 20);
  const root = useRef<HTMLDivElement>(null);
  const option = useMemo<EChartsOption>(() => {
    if (!data) return {};
    const selected = data.values.slice(-features), labels = data.features.slice(-features), samples = data.samples.slice(0, compact ? 28 : 60);
    const max = Math.max(1, Math.ceil(Math.max(...selected.flat().map(Math.abs))));
    return { tooltip: { position: 'top', formatter: (p: unknown) => { const val = (p as { value: number[] }).value; const s = transpose ? val[1] : val[0], f = transpose ? val[0] : val[1]; return `样本：${samples[s]}\n特征：${labels[f]}\nZ-score：${val[2]}`; } },
      grid: { left: compact ? 98 : transpose ? 98 : 130, right: compact ? 16 : 35, top: 14, bottom: 62 },
      toolbox: { feature: { saveAsImage: { title: '导出热图', pixelRatio: 2, name: 'GeneScope_expression_heatmap' } }, right: 6 },
      xAxis: { type: 'category', data: transpose ? labels : samples, axisLabel: { show: !compact, rotate: 45, fontSize: 11 }, axisTick: { show: false }, axisLine: { show: false } },
      yAxis: { type: 'category', data: transpose ? samples : labels, axisLabel: { fontSize: 11 }, axisTick: { show: false }, axisLine: { show: false } },
      visualMap: { min: -max, max, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 10, itemHeight: compact ? 100 : 150, calculable: !compact, textStyle: { fontSize: 11 }, inRange: { color: ['#a395f2', '#f5f8ff', '#60d9c0'] } },
      dataZoom: compact ? [] : [{ type: 'inside', xAxisIndex: 0 }, { type: 'inside', yAxisIndex: 0 }],
      series: [{ type: 'heatmap', data: selected.flatMap((row, y) => row.slice(0, samples.length).map((value, x) => [transpose ? y : x, transpose ? x : y, Number(value.toFixed(3))])), itemStyle: { borderColor: '#ffffff', borderWidth: .7 }, emphasis: { itemStyle: { borderWidth: 2, borderColor: '#7c76ed' } } }],
    };
  }, [data, compact, features, transpose]);
  if (!data) return <EmptyState title="暂无表达热图" description="数据集导入后显示真实表达矩阵" />;
  return <div className={`heatmap-explorer ${compact ? 'heatmap-compact' : ''}`} ref={root}><div className="heatmap-toolbar"><span className="small-note">高方差特征 · 行方向 Z-score</span><Space size={5}>{!compact && <><Select aria-label="热图特征数量" size="mini" value={features} onChange={setFeatures} options={[10, 20].filter(n => n <= data.features.length).map(n => ({ value: n, label: `Top ${n}` }))} style={{ width: 92 }} /><Button size="mini" onClick={() => setTranspose(v => !v)}>切换视图</Button></>}<Tooltip content="全屏查看"><Button size="mini" aria-label="全屏查看热图" icon={<Icon name="expand" size={14} />} onClick={() => { if (document.fullscreenElement) void document.exitFullscreen(); else void root.current?.requestFullscreen(); }} /></Tooltip></Space></div><EChart option={option} style={{ height: compact ? 245 : transpose ? 580 : 390 }} /><p className="small-note">行方向 Z-score；当前显示 {Math.min(features, data.features.length)} 特征 × {Math.min(compact ? 28 : 60, data.samples.length)} 样本。</p></div>;
}

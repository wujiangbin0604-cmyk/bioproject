import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { EChart } from '../EChart';
import type { Fold } from '../../api/platform';
import { names } from '../../api/platform';
import { metricNames } from '../../utils/platform';
export function RealTimeChart({ folds, metrics = ['macro_f1', 'balanced_accuracy', 'accuracy'], time = false }: { folds: Fold[]; metrics?: string[]; time?: boolean }) {
  const option = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: 'axis' }, legend: { top: 4, itemWidth: 12, itemHeight: 7, textStyle: { fontSize: 11 } },
    toolbox: { right: 4, feature: { saveAsImage: { title: '导出图表', pixelRatio: 2, name: 'GeneScope_fold_metrics' } } },
    grid: { top: 48, bottom: folds.length > 8 ? 65 : 38, left: 50, right: 25 },
    xAxis: { type: 'category', boundaryGap: false, data: folds.map(f => `${names[f.algorithm]} R${f.repeat} F${f.fold}`), axisLabel: { show: folds.length < 9, fontSize: 11 }, axisTick: { show: false }, axisLine: { lineStyle: { color: '#dce6f6' } } },
    yAxis: { type: 'value', min: 0, max: time ? undefined : 1, name: time ? '秒' : undefined, splitLine: { lineStyle: { color: '#edf2fb' } } },
    dataZoom: folds.length > 8 ? [{ type: 'inside' }, { type: 'slider', height: 13, bottom: 6 }] : [],
    series: (time ? ['fit_seconds'] : metrics).map((key, i) => ({ id: key, name: metricNames[key], type: 'line', smooth: .2, symbol: 'circle', symbolSize: 6, data: folds.map(f => Number(f[key as keyof Fold])), lineStyle: { width: 2 }, areaStyle: { opacity: .045 }, itemStyle: { color: ['#4285f4', '#35c8ab', '#a58af2'][i] } })),
  }), [folds, metrics, time]);
  return <EChart option={option} notMerge={false} style={{ height: 310 }} />;
}

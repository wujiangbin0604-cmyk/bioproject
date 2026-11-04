import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import type { Config, Dataset, Result } from '../../api/platform';
import { names } from '../../api/platform';
import { EChart } from '../EChart';

export interface OverviewRow extends Result { config: Config; task?: string }
const colors = ['#4c8df6', '#35c8b7', '#a58bf5'];

export function OverviewAnalysisChart({ tab, rows, latestTaskId, dataset }: {
  tab: string; rows: OverviewRow[]; latestTaskId?: string; dataset?: Dataset;
}) {
  const option = useMemo<EChartsOption>(() => {
    const toolbox = { right: 0, top: 1, itemSize: 15, iconStyle: { borderColor: '#91a9cc' },
      feature: { saveAsImage: { title: '导出分析图', pixelRatio: 2, name: `GeneScope_${dataset?.dataset_id ?? 'analysis'}_${tab}` } } };
    if (tab === 'distribution') return {
      color: [...colors, '#71c6ef', '#f2c278'], toolbox,
      tooltip: { trigger: 'item', formatter: '{b}\n{c} 例 · {d}%' },
      legend: { orient: 'vertical', right: 30, top: 'center', itemWidth: 10, itemHeight: 10, itemGap: 15, textStyle: { fontSize: 12, color: '#557397' } },
      series: [{ type: 'pie', radius: ['43%', '73%'], center: ['35%', '49%'], label: { show: false },
        emphasis: { scaleSize: 5, label: { show: true, fontSize: 14, fontWeight: 600 } },
        itemStyle: { borderWidth: 4, borderColor: '#f8fbff', borderRadius: 5 },
        data: Object.entries(dataset?.class_counts ?? {}).map(([name, value]) => ({ name, value })) }],
    };
    const features = tab === 'features', data = features ? rows : rows.filter(row => row.task === latestTaskId);
    return {
      color: colors, toolbox, animationDuration: 650, animationDurationUpdate: 350,
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: '#dcecff3b' } },
        valueFormatter: (value: unknown) => typeof value === 'number' ? value.toFixed(4) : String(value) },
      legend: { left: 8, top: 5, itemWidth: 13, itemHeight: 8, itemGap: 19, textStyle: { fontSize: 12, color: '#557397' } },
      grid: { left: 42, top: 46, right: 12, bottom: features ? 84 : 58 },
      xAxis: { type: 'category', data: data.map(row => features ? `${names[row.algorithm]}\nK=${row.config.selection === 'none' ? '全部' : row.config.k}\n${row.task?.slice(0, 6)}` : row.algorithm === 'logistic_regression' ? 'Logistic\nRegression' : row.algorithm === 'random_forest' ? 'Random\nForest' : names[row.algorithm]),
        axisTick: { show: false }, axisLine: { lineStyle: { color: '#dae7f8' } }, axisLabel: { fontSize: 11, color: '#637c9f', interval: 0, margin: 13, lineHeight: 17 } },
      yAxis: { type: 'value', min: 0, max: 1, axisLabel: { fontSize: 12, color: '#6d84a4' },
        splitLine: { lineStyle: { color: '#e6eef9', type: 'dashed' } } },
      dataZoom: features && data.length > 8 ? [{ type: 'inside' }, { type: 'slider', height: 12, bottom: 0, start: 0, end: Math.min(100, 800 / data.length) }] : [],
      series: (features ? ['jaccard'] : ['macro_f1', 'balanced_accuracy', 'accuracy']).map((key, i) => ({
        id: key, type: 'bar', name: key === 'jaccard' ? 'CV训练折 Jaccard' : ['Macro-F1', 'Balanced Accuracy', 'Accuracy'][i],
        barMaxWidth: features ? 30 : 22, barGap: '22%',
        emphasis: { focus: 'series', itemStyle: { shadowBlur: 8, shadowColor: `${colors[i]}44` } },
        itemStyle: { borderRadius: [5, 5, 0, 0], color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: colors[i] }, { offset: 1, color: ['#88bcff', '#8be6d4', '#c6b4ff'][i] }] } },
        data: data.map(row => key === 'jaccard' ? row.jaccard_mean : row.metrics[key].mean),
      })),
    };
  }, [tab, rows, latestTaskId, dataset]);
  return <EChart option={option} style={{ height: 275 }} />;
}

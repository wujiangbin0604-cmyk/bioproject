import type { Result } from '../../api/platform';
import { EChart } from '../EChart';
export function ConfusionMatrix({ result }: { result: Result }) {
  const max = Math.max(1, ...result.confusion_matrix.flat());
  return <EChart style={{ height: 340 }} option={{ tooltip: { formatter: p => { const v = (p as unknown as { value: number[] }).value; return `真实类别：${result.labels[v[1]]}\n预测类别：${result.labels[v[0]]}\n样本计数：${v[2]}`; } },
    toolbox: { feature: { saveAsImage: { title: '导出混淆矩阵', name: 'GeneScope_confusion', pixelRatio: 2 } } }, grid: { top: 24, bottom: 65, left: 100, right: 30 },
    xAxis: { type: 'category', data: result.labels, axisLabel: { fontSize: 11, interval: 0, rotate: 20 }, name: '预测' }, yAxis: { type: 'category', data: result.labels, axisLabel: { fontSize: 11 }, name: '真实' },
    visualMap: { min: 0, max, orient: 'horizontal', left: 'center', bottom: 0, itemHeight: 130, itemWidth: 10, inRange: { color: ['#f1f6ff', '#abd3ff', '#4285f4'] } },
    series: [{ type: 'heatmap', data: result.confusion_matrix.flatMap((row, y) => row.map((v, x) => [x, y, v])), label: { show: true, fontSize: 12 }, itemStyle: { borderWidth: 3, borderColor: '#fff', borderRadius: 5 }, emphasis: { itemStyle: { borderColor: '#a48bf5', borderWidth: 3 } } }],
  }} />;
}

import type { CSSProperties } from 'react';
import type { EChartsOption } from 'echarts';
import * as echarts from 'echarts/core';
import { BarChart, HeatmapChart, LineChart, PieChart } from 'echarts/charts';
import { AxisPointerComponent, GridComponent, LegendComponent, MarkPointComponent, TooltipComponent, VisualMapComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import type { Opts } from 'echarts-for-react/lib/types';

echarts.use([
  BarChart, HeatmapChart, LineChart, PieChart,
  AxisPointerComponent, GridComponent, LegendComponent, MarkPointComponent, TooltipComponent, VisualMapComponent,
  CanvasRenderer,
]);

export function EChart({ option, style, notMerge = true, lazyUpdate = true, opts }: {
  option: EChartsOption; style?: CSSProperties; notMerge?: boolean; lazyUpdate?: boolean; opts?: Opts;
}) {
  // 关闭默认绘制动画，避免快速导航或截图时图表只显示动画中间帧。
  const stableOption: EChartsOption = { ...option, animation: false };
  return <ReactEChartsCore echarts={echarts} option={stableOption} style={style} notMerge={notMerge} lazyUpdate={lazyUpdate} opts={opts} />;
}

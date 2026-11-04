import { useEffect, useMemo, useRef } from 'react';
import type { CSSProperties } from 'react';
import type { EChartsOption } from 'echarts';
import * as echarts from 'echarts/core';
import { BarChart, HeatmapChart, LineChart, PieChart, ScatterChart } from 'echarts/charts';
import { AxisPointerComponent, DataZoomComponent, GridComponent, LegendComponent, MarkPointComponent, ToolboxComponent, TooltipComponent, VisualMapComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import type { Opts } from 'echarts-for-react/lib/types';
import { usePreferences } from '../hooks/usePreferences';
import { motionConfig } from '../animations/motionConfig';

echarts.use([
  BarChart, HeatmapChart, LineChart, PieChart, ScatterChart,
  AxisPointerComponent, DataZoomComponent, GridComponent, LegendComponent, MarkPointComponent, ToolboxComponent, TooltipComponent, VisualMapComponent,
  CanvasRenderer,
]);

export function EChart({ option, style, notMerge = true, lazyUpdate = true, opts }: {
  option: EChartsOption; style?: CSSProperties; notMerge?: boolean; lazyUpdate?: boolean; opts?: Opts;
}) {
  const wrapper = useRef<HTMLDivElement>(null), instance = useRef<ReactEChartsCore>(null);
  const { reduced, visible, settings } = usePreferences();
  const stableOption = useMemo<EChartsOption>(() => ({
    color: ['#4c8df6', '#35c8b7', '#a58bf5', '#63b8f6', '#f3b55d'],
    textStyle: { fontFamily: 'Segoe UI, Microsoft YaHei, sans-serif', color: settings.theme === 'dark' ? '#cad7ef' : '#637b9d', fontSize: 12 },
    animationDuration: motionConfig.chart, animationDurationUpdate: motionConfig.page,
    ...option,
    animation: !reduced && visible && option.animation !== false,
    tooltip: { renderMode: 'richText', backgroundColor: settings.theme === 'dark' ? '#23324b' : 'rgba(255,255,255,.97)', borderColor: '#d7e5fb', borderWidth: 1, padding: [11, 14], shadowBlur: 18, shadowColor: '#527dbb20', shadowOffsetY: 5, textStyle: { fontSize: 12, lineHeight: 19, color: settings.theme === 'dark' ? '#cad7ef' : '#3d587d' }, ...(!Array.isArray(option.tooltip) ? option.tooltip : {}) },
  }), [option, reduced, visible, settings.theme]);
  useEffect(() => {
    let frame = 0;
    const observer = new ResizeObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => instance.current?.getEchartsInstance().resize()); });
    if (wrapper.current) observer.observe(wrapper.current);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, []);
  return <div className="chart-resize-container" ref={wrapper} style={style}><ReactEChartsCore ref={instance} echarts={echarts} option={stableOption} style={{ height: '100%', width: '100%' }} notMerge={notMerge} replaceMerge={notMerge ? undefined : ['series']} lazyUpdate={lazyUpdate} opts={opts} /></div>;
}

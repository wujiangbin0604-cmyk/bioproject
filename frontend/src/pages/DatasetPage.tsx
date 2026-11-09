import { useMemo } from 'react';
import { Alert, Card, Grid, Skeleton, Tag } from '@arco-design/web-react';
import type { EChartsOption } from 'echarts';
import { useApi } from '../hooks';
import type { DatasetSummary, HeatmapList } from '../types/api';
import { ChartPanel } from '../components/ChartPanel';
import { MetricCard } from '../components/MetricCard';
import { PageHeading } from '../components/PageHeading';
import { RemotePanel, SourceNote } from '../components/RemotePanel';
import { CLASS_COLORS, PALETTE } from '../constants';

export function DatasetPage() {
  const summary = useApi<DatasetSummary>('/api/v1/dataset/summary');
  const heatmaps = useApi<HeatmapList>('/api/v1/dataset/heatmaps');
  const data = summary.envelope?.data;

  const distributionOption = useMemo<EChartsOption>(() => {
    const classes = data?.classes ?? [];
    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 48, right: 22, top: 26, bottom: 70 },
      xAxis: { type: 'category', data: classes.map((item) => item.code), axisTick: { show: false }, axisLabel: { color: '#607681' } },
      yAxis: { type: 'value', name: '样本数', splitLine: { lineStyle: { color: PALETTE.grid } } },
      series: [{ type: 'bar', barWidth: 38, data: classes.map((item) => ({ value: item.sample_count, itemStyle: { color: CLASS_COLORS[item.code] ?? PALETTE.blue, borderRadius: [5, 5, 0, 0] } })), label: { show: true, position: 'top', color: PALETTE.ink, fontWeight: 600 } }],
    };
  }, [data]);

  const splitOption = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: 'item', formatter: '{b}<br/>{c}例（{d}%）' },
    legend: { bottom: 2, left: 'center', itemWidth: 10, itemHeight: 10 },
    series: [{ type: 'pie', radius: ['55%', '78%'], center: ['50%', '43%'], avoidLabelOverlap: true,
      label: { formatter: '{b}\n{d}%', color: '#465A65' },
      data: [{ name: '开发集', value: data?.split.development_samples ?? 0, itemStyle: { color: PALETTE.blue } },
        { name: '回顾性保留集', value: data?.split.reserved_samples ?? 0, itemStyle: { color: PALETTE.teal } }],
    }],
  }), [data]);

  const qualityLabels: Array<[string, keyof NonNullable<DatasetSummary['quality']>]> = [
    ['缺失表达值', 'missing_values'], ['无穷表达值', 'infinite_values'], ['重复样本ID', 'duplicate_expression_ids'],
    ['重复表达谱', 'duplicate_expression_profiles'], ['非数值列', 'nonnumeric_columns'],
  ];

  return <div className="page-stack">
    <PageHeading eyebrow="DATA EXPLORATION" title="RNA-Seq 数据探索" description="查看 UCI Dataset 401 的样本组成、固定划分与质量检查摘要。" />
    <div className="metric-grid four">
      <MetricCard label="总样本" value={data?.dataset.samples ?? '—'} detail="UCI Gene Expression Cancer RNA-Seq" accent="blue" />
      <MetricCard label="基因特征" value={data?.dataset.genes?.toLocaleString() ?? '—'} detail="保留原始 gene_* 匿名标识" accent="teal" />
      <MetricCard label="开发集" value={data?.split.development_samples ?? '—'} detail="分层划分 · random_state=42" accent="ink" />
      <MetricCard label="保留集" value={data?.split.reserved_samples ?? '—'} detail="回顾性同源评价" accent="amber" />
    </div>
    <Grid.Row gutter={[16, 16]}>
      <Grid.Col xs={24} lg={15}><ChartPanel title="五类癌症样本分布" subtitle="真实类别计数，颜色在全站保持一致。" option={distributionOption} loading={summary.loading} error={summary.error} status={summary.envelope?.status} empty={!data?.classes.length} height={330} /></Grid.Col>
      <Grid.Col xs={24} lg={9}><ChartPanel title="固定开发 / 保留划分" subtitle="80%开发集与20%回顾性保留集。" option={splitOption} loading={summary.loading} error={summary.error} status={summary.envelope?.status} empty={!data?.split.development_samples} height={330} /></Grid.Col>
    </Grid.Row>
    <Card className="panel-card" bordered={false} title={<div><div className="panel-title">数据质量检查</div><div className="panel-subtitle">来自项目已保存的数据质量报告</div></div>}>
      <RemotePanel loading={summary.loading} error={summary.error} status={summary.envelope?.status}>
        <div className="quality-grid">{qualityLabels.map(([label, field]) => <div className="quality-item" key={field}>
          <span>{label}</span><strong>{String(data?.quality[field] ?? '—')}</strong>
          <Tag color={data?.quality[field] === 0 ? 'green' : 'gray'}>{data?.quality[field] === 0 ? '通过' : '报告值'}</Tag>
        </div>)}</div>
        <div className="alignment-note"><span className="check-mark">✓</span>样本标签按 sample ID 对齐；原始样本顺序与标签顺序一致。</div>
      </RemotePanel>
      <SourceNote source={summary.envelope?.source} />
    </Card>
    <section className="section-block">
      <div className="section-row"><div><div className="eyebrow">EXPLORATORY HEATMAPS</div><h2>开发集表达模式热图</h2></div><Tag color="arcoblue">仅 640 例开发集</Tag></div>
      <Alert type="info" title="表达热图" content="样本列按癌种顺序排列，每个基因按行进行 Z-score 标准化。Top50 按开发集方差或 ANOVA F-score 选择。" />
      {heatmaps.loading ? <Skeleton loading={true} animation /> : heatmaps.error ? <Alert type="error" content={heatmaps.error} /> : heatmaps.envelope?.status === 'unavailable' ? <Alert type="warning" content="热图文件尚未导入，请导入表达热图后查看。" /> : <Grid.Row gutter={[16, 16]} className="heatmap-grid">
        {(heatmaps.envelope?.data.images ?? []).map((image) => <Grid.Col xs={24} key={image.method}>
          <Card className="panel-card heatmap-card" bordered={false} title={<div><div className="panel-title">{image.name}</div><div className="panel-subtitle">{image.standardization} · {image.sample_order}</div></div>}>
            {image.status === 'available' && image.url ? <img src={image.url} alt={`${image.name}表达热图`} loading="lazy" /> : <div className="remote-state">热图文件尚未导入</div>}
          </Card>
        </Grid.Col>)}
      </Grid.Row>}
    </section>
  </div>;
}

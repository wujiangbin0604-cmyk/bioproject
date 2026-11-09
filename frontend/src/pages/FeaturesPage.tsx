import { useMemo, useState } from 'react';
import { Card, Grid, Select, Table, Tag } from '@arco-design/web-react';
import type { EChartsOption } from 'echarts';
import { useApi } from '../hooks';
import type { GeneFrequencyData, PerformanceData, StabilityData } from '../types/api';
import { ChartPanel } from '../components/ChartPanel';
import { PageHeading } from '../components/PageHeading';
import { RemotePanel, SourceNote } from '../components/RemotePanel';
import { K_VALUES, PALETTE } from '../constants';

const METHOD_NAMES: Record<string, string> = { anova: 'ANOVA F-score', variance: '高方差', logistic: 'ANOVA + Logistic Regression', full: '全特征 Linear SVM' };

export function FeaturesPage() {
  const [method, setMethod] = useState('anova');
  const [k, setK] = useState(50);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const performance = useApi<PerformanceData>('/api/v1/features/performance', { method });
  const stabilityMethod = method === 'variance' ? 'variance' : method === 'anova' ? 'anova' : 'all';
  const stability = useApi<StabilityData>('/api/v1/features/stability', { method: stabilityMethod, k });
  const genes = useApi<GeneFrequencyData>('/api/v1/features/genes', { method: stabilityMethod === 'all' ? 'anova' : stabilityMethod, k, search, page, page_size: 12, sort_by: 'selection_frequency', descending: true });

  const rows = performance.envelope?.data.records ?? [];
  const methodRows = rows.filter((row) => method === 'full' ? row.method === 'full_svm' : method === 'logistic' ? row.method === 'anova_lr' : row.method === `${method}_svm`);
  const perfOption = useMemo<EChartsOption>(() => ({
    color: [PALETTE.blue, PALETTE.teal],
    tooltip: { trigger: 'axis', valueFormatter: (value) => `${(Number(value) * 100).toFixed(3)}%` },
    legend: { top: 0, data: ['Macro-F1', 'Balanced Accuracy'] },
    grid: { left: 55, right: 20, top: 42, bottom: 35 },
    xAxis: { type: 'category', name: 'K', data: methodRows.map((row) => row.k === 20531 ? '全部' : String(row.k)), axisTick: { show: false } },
    yAxis: { type: 'value', min: 0.94, max: 1.005, axisLabel: { formatter: (value) => `${(Number(value) * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: PALETTE.grid } } },
    series: [
      { name: 'Macro-F1', type: 'line', data: methodRows.map((row) => row.validation_macro_f1_mean), symbolSize: 8, smooth: 0.25, lineStyle: { width: 2.5 } },
      { name: 'Balanced Accuracy', type: 'line', data: methodRows.map((row) => row.validation_balanced_accuracy_mean), symbolSize: 8, smooth: 0.25, lineStyle: { width: 2.5 } },
    ],
  }), [methodRows]);

  const stabilityRows = stability.envelope?.data.records ?? [];
  const stabilityOption = useMemo<EChartsOption>(() => ({
    color: [PALETTE.teal, PALETTE.amber],
    tooltip: { trigger: 'axis' }, legend: { top: 0, data: ['Jaccard', 'Kuncheva'] },
    grid: { left: 45, right: 20, top: 42, bottom: 35 }, xAxis: { type: 'category', data: stabilityRows.map((row) => String(row.method)), axisLabel: { interval: 0, rotate: 10 } },
    yAxis: { type: 'value', min: 0, max: 1, splitLine: { lineStyle: { color: PALETTE.grid } } },
    series: [{ name: 'Jaccard', type: 'bar', barWidth: 28, data: stabilityRows.map((row) => row.jaccard_mean) }, { name: 'Kuncheva', type: 'bar', barWidth: 28, data: stabilityRows.map((row) => row.kuncheva_mean) }],
  }), [stabilityRows]);

  const geneRows = genes.envelope?.data.records ?? [];
  const columns = [
    { title: '匿名特征', dataIndex: 'gene_id', render: (value: string) => <code className="gene-id">{value}</code> },
    { title: '入选次数', dataIndex: 'selection_count', width: 92 },
    { title: '入选频率', dataIndex: 'selection_frequency', width: 110, render: (value: number) => `${(value * 100).toFixed(1)}%` },
    { title: '入选时平均排名', dataIndex: 'mean_rank_when_selected', width: 140, render: (value: number) => Number(value).toFixed(1) },
  ];

  return <div className="page-stack">
    <PageHeading eyebrow="FEATURE SELECTION & STABILITY" title="特征选择与稳定性" description="比较开发集内不同 K 和筛选方法的真实交叉验证表现，并查看 30 次分层子采样的特征集合稳定性。" extra={<Tag color="arcoblue">特征选择在训练折内拟合</Tag>} />
    <Card className="panel-card controls-card" bordered={false}>
      <div className="controls-row"><div><label>筛选方法</label><Select value={method} onChange={setMethod} style={{ width: 250 }}>
        {Object.entries(METHOD_NAMES).map(([value, label]) => <Select.Option key={value} value={value}>{label}</Select.Option>)}
      </Select></div><div><label>特征数量 K</label><Select value={k} onChange={(value) => { setK(Number(value)); setPage(1); }} style={{ width: 150 }}>
        {K_VALUES.map((value) => <Select.Option key={value} value={value}>{value}</Select.Option>)}
      </Select></div><div className="control-context">全特征方案固定为20,531列；该页面只读取已完成的开发集记录。</div></div>
    </Card>
    <Grid.Row gutter={[16, 16]}>
      <Grid.Col xs={24} xl={15}><ChartPanel title={`${METHOD_NAMES[method]} 分类性能曲线`} subtitle="5折 × 20轮重复交叉验证。" option={perfOption} loading={performance.loading} error={performance.error} status={performance.envelope?.status} empty={!methodRows.length} height={340} /></Grid.Col>
      <Grid.Col xs={24} xl={9}><ChartPanel title="特征选择稳定性" subtitle={`K=${k} · 开发集30次分层子采样`} option={stabilityOption} loading={stability.loading} error={stability.error} status={stability.envelope?.status} empty={!stabilityRows.length} height={340} /></Grid.Col>
    </Grid.Row>
    <div className="source-row"><SourceNote source={performance.envelope?.source} /><SourceNote source={stability.envelope?.source} /></div>
    <Card className="panel-card" bordered={false} title={<div><div className="panel-title">特征入选频率</div><div className="panel-subtitle">{METHOD_NAMES[stabilityMethod === 'all' ? 'anova' : stabilityMethod]} · K={k} · 搜索 gene_* 匿名特征</div></div>}>
      <div className="table-toolbar"><input className="search-input" aria-label="搜索基因特征" placeholder="搜索 gene_…" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} /><span className="muted-inline">{genes.envelope?.data.total ?? 0} 个结果</span></div>
      <RemotePanel loading={genes.loading} error={genes.error} status={genes.envelope?.status} empty={!geneRows.length}>
        <Table rowKey="gene_id" columns={columns} data={geneRows} pagination={{ current: page, pageSize: 12, total: genes.envelope?.data.total ?? 0, onChange: setPage, sizeCanChange: false }} />
      </RemotePanel>
      <div className="table-note">gene_* 为原始匿名特征标识。</div>
    </Card>
  </div>;
}

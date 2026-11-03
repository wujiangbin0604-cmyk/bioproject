import { useMemo, useState } from 'react';
import { Alert, Card, Grid, Select, Table, Tag } from '@arco-design/web-react';
import type { EChartsOption } from 'echarts';
import { useApi } from '../hooks';
import type { ConfusionData, ErrorAnalysis, ModelComparisonData, PerClassData } from '../types/api';
import { ChartPanel } from '../components/ChartPanel';
import { EChart } from '../components/EChart';
import { PageHeading } from '../components/PageHeading';
import { RemotePanel, SourceNote } from '../components/RemotePanel';
import { CLASS_LABELS, PALETTE } from '../constants';

const MODELS = [
  { id: 'M0', name: '全特征 LinearSVC', features: '20,531' },
  { id: 'M1', name: 'ANOVA Top50 + LinearSVC', features: '50' },
  { id: 'M2', name: '高方差 Top20 + LinearSVC', features: '20' },
  { id: 'M3', name: 'ANOVA Top300 + LinearSVC', features: '300' },
  { id: 'M4', name: 'ANOVA Top50 + 高方差补充30', features: '80' },
  { id: 'M5', name: 'ANOVA / 方差 / Logistic 三模型硬投票', features: '每折特征并集' },
];

export function ModelsPage() {
  const [selected, setSelected] = useState('M1');
  const comparison = useApi<ModelComparisonData>('/api/v1/models/comparison');
  const perClass = useApi<PerClassData>('/api/v1/models/per-class');
  const confusion = useApi<ConfusionData>('/api/v1/models/confusion-matrix', { model_id: selected });
  const errors = useApi<ErrorAnalysis>('/api/v1/models/errors');
  const models = comparison.envelope?.data.models ?? [];
  const perClassRows = perClass.envelope?.data.records ?? [];
  const availableIds = new Set(models.map((row) => String(row.model)));
  const modelColumns = [
    { title: '模型', dataIndex: 'model', width: 76, render: (value: string) => <span className={value === 'M1' ? 'primary-model-id' : 'model-id'}>{value}</span> },
    { title: '配置', dataIndex: 'model_name', render: (value: string) => <span className="table-model-name">{value}</span> },
    { title: '独立基因数', dataIndex: 'n_unique_genes', width: 116, render: (value: number) => Number(value).toLocaleString() },
    { title: 'Accuracy', dataIndex: 'accuracy', width: 110, render: (value: number) => `${(Number(value) * 100).toFixed(2)}%` },
    { title: 'Macro-F1', dataIndex: 'macro_f1', width: 110, render: (value: number) => <strong>{(Number(value) * 100).toFixed(2)}%</strong> },
    { title: 'Balanced Acc.', dataIndex: 'balanced_accuracy', width: 120, render: (value: number) => `${(Number(value) * 100).toFixed(2)}%` },
    { title: '错误数', dataIndex: 'n_errors', width: 85 },
  ];

  const compareOption = useMemo<EChartsOption>(() => ({
    color: [PALETTE.blue, PALETTE.teal, PALETTE.amber],
    tooltip: { trigger: 'axis', valueFormatter: (value) => `${(Number(value) * 100).toFixed(2)}%` },
    legend: { top: 0, data: ['Accuracy', 'Macro-F1', 'Balanced Accuracy'] }, grid: { left: 50, right: 20, top: 40, bottom: 34 },
    xAxis: { type: 'category', data: models.map((item) => String(item.model)), axisTick: { show: false } },
    yAxis: { type: 'value', min: 0.92, max: 1.005, axisLabel: { formatter: (value) => `${(Number(value) * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: PALETTE.grid } } },
    series: [
      { name: 'Accuracy', type: 'bar', barMaxWidth: 18, data: models.map((item) => item.accuracy) },
      { name: 'Macro-F1', type: 'bar', barMaxWidth: 18, data: models.map((item) => item.macro_f1) },
      { name: 'Balanced Accuracy', type: 'bar', barMaxWidth: 18, data: models.map((item) => item.balanced_accuracy) },
    ],
  }), [models]);

  const perClassOption = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: 'axis', valueFormatter: (value) => `${(Number(value) * 100).toFixed(1)}%` },
    legend: { type: 'scroll', top: 0, data: MODELS.filter((model) => availableIds.has(model.id)).map((model) => model.id) },
    grid: { left: 60, right: 20, top: 46, bottom: 44 },
    xAxis: { type: 'category', data: ['BRCA', 'KIRC', 'COAD', 'LUAD', 'PRAD'].map((code) => `${code}\n${CLASS_LABELS[code]}`), axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', min: 0.7, max: 1.01, axisLabel: { formatter: (value) => `${(Number(value) * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: PALETTE.grid } } },
    series: MODELS.filter((model) => availableIds.has(model.id)).map((model) => ({ name: model.id, type: 'bar', barMaxWidth: 17, data: ['BRCA', 'KIRC', 'COAD', 'LUAD', 'PRAD'].map((code) => Number(perClassRows.find((row) => row.model === model.id && row.cancer_type === code)?.f1 ?? 0)) })),
  }), [perClassRows, availableIds]);

  const matrix = confusion.envelope?.data.matrix ?? [];
  const heatValues = matrix.flatMap((row, y) => row.map((value, x) => [x, y, value]));
  const confusionOption: EChartsOption = {
    tooltip: { position: 'top', formatter: (item: any) => `${confusion.envelope?.data.classes[item.data[1]]?.code} → ${confusion.envelope?.data.classes[item.data[0]]?.code}<br/>${item.data[2]} 例` },
    grid: { left: 88, right: 22, top: 18, bottom: 60 },
    xAxis: { type: 'category', data: confusion.envelope?.data.classes.map((item) => item.code) ?? [], name: '预测类别', nameLocation: 'middle', nameGap: 36 },
    yAxis: { type: 'category', data: confusion.envelope?.data.classes.map((item) => item.code) ?? [], inverse: true, name: '真实类别', nameLocation: 'middle', nameGap: 58 },
    visualMap: { min: 0, max: Math.max(1, ...matrix.flat()), calculable: false, orient: 'horizontal', left: 'center', bottom: 2, inRange: { color: ['#F3F6F7', '#A8D4CE', PALETTE.teal] } },
    series: [{ type: 'heatmap', data: heatValues, label: { show: true, color: PALETTE.ink }, itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 3 } }],
  };

  const errorRows = errors.envelope?.data.shared_error_counts ?? [];
  const overlapOption: EChartsOption = {
    tooltip: { trigger: 'axis' }, grid: { left: 55, right: 16, top: 18, bottom: 68 },
    xAxis: { type: 'category', data: errorRows.map((row) => `${row.model_a}/${row.model_b}`), axisLabel: { rotate: 50, fontSize: 9 } },
    yAxis: { type: 'value', name: '共同错误样本数', minInterval: 1, splitLine: { lineStyle: { color: PALETTE.grid } } },
    series: [{ type: 'bar', barMaxWidth: 22, data: errorRows.map((row) => row.shared_error_sample_count), itemStyle: { color: PALETTE.coral, borderRadius: [4, 4, 0, 0] } }],
  };

  return <div className="page-stack">
    <PageHeading eyebrow="MODEL EVALUATION" title="模型性能对比" description="按预先冻结的 M0–M5 顺序展示同源回顾性保留集结果，并与开发集重复交叉验证摘要并列查看。" extra={<Tag color="orange">保留集为回顾性评价</Tag>} />
    <Alert type="warning" title="结果解释边界" content={comparison.envelope?.data.test_scope ?? '保留集不属于跨机构外部验证；开发集100个重复折具有相关性，不能作为100个独立样本进行推断。'} />
    <Card className="panel-card" bordered={false} title={<div><div className="panel-title">M0–M5 回顾性保留集指标</div><div className="panel-subtitle">实际独立特征数、错误数与分类性能</div></div>}>
      <RemotePanel loading={comparison.loading} error={comparison.error} status={comparison.envelope?.status} empty={!models.length}>
        <Table rowKey="model" columns={modelColumns} data={models} pagination={false} />
      </RemotePanel>
      <SourceNote source={comparison.envelope?.source} note={comparison.envelope?.data.cv_scope} />
    </Card>
    <Grid.Row gutter={[16, 16]}>
      <Grid.Col xs={24} xl={12}><ChartPanel title="六模型整体性能" subtitle="回顾性161例保留集；展示三个指标。" option={compareOption} loading={comparison.loading} error={comparison.error} status={comparison.envelope?.status} empty={!models.length} height={340} /></Grid.Col>
      <Grid.Col xs={24} xl={12}><ChartPanel title="五类别 F1 对比" subtitle="逐类别 F1，类别名称及配色沿用数据探索页。" option={perClassOption} loading={perClass.loading} error={perClass.error} status={perClass.envelope?.status} empty={!perClassRows.length} height={340} /></Grid.Col>
    </Grid.Row>
    <Grid.Row gutter={[16, 16]}>
      <Grid.Col xs={24} xl={12}>
        <Card className="panel-card" bordered={false} title={<div><div className="panel-title">主要模型混淆矩阵</div><div className="panel-subtitle">选择冻结模型查看真实计数</div></div>} extra={<Select value={selected} onChange={setSelected} style={{ width: 92 }}>{MODELS.map((model) => <Select.Option key={model.id} value={model.id}>{model.id}</Select.Option>)}</Select>}>
          <RemotePanel loading={confusion.loading} error={confusion.error} status={confusion.envelope?.status} empty={!matrix.length}><EChart option={confusionOption} notMerge lazyUpdate style={{ height: 315 }} /></RemotePanel>
        </Card>
      </Grid.Col>
      <Grid.Col xs={24} xl={12}><ChartPanel title="错误样本重合" subtitle="仅显示错误事件的聚合重合数，不公开样本ID。" option={overlapOption} loading={errors.loading} error={errors.error} status={errors.envelope?.status} empty={!errorRows.length} height={370} /></Grid.Col>
    </Grid.Row>
    <Card className="panel-card" bordered={false} title={<div><div className="panel-title">相对 M1 的纠错与新增错误</div><div className="panel-subtitle">小样本错误事件仅作描述性比较</div></div>}>
      <RemotePanel loading={errors.loading} error={errors.error} status={errors.envelope?.status} empty={!errors.envelope?.data.relative_to_M1.length}>
        <Table rowKey="model" pagination={false} data={errors.envelope?.data.relative_to_M1 ?? []} columns={[
          { title: '对照模型', dataIndex: 'model' }, { title: '相对M1纠正', dataIndex: 'corrected_vs_M1' }, { title: '相对M1新增错误', dataIndex: 'new_errors_vs_M1' },
        ]} />
      </RemotePanel>
    </Card>
    <div className="notice-callout"><strong>冻结模型顺序：</strong>{MODELS.map((model) => `${model.id} ${model.name}`).join(' · ')}。测试结果仅用于此次最终评价，不用于修改参数或选择新的主模型。</div>
  </div>;
}

import { useMemo } from 'react';
import { Alert, Card, Grid, Table, Tag } from '@arco-design/web-react';
import type { EChartsOption } from 'echarts';
import { useApi } from '../hooks';
import type { FusionData } from '../types/api';
import { ChartPanel } from '../components/ChartPanel';
import { PageHeading } from '../components/PageHeading';
import { RemotePanel, SourceNote } from '../components/RemotePanel';
import { PALETTE } from '../constants';

const SCHEME_NAMES: Record<string, string> = {
  anova_k50: 'ANOVA Top50', variance_k50: '高方差 Top50', fusion_equal_k50: '等额融合 Top50',
  fusion_anova75_k50: 'ANOVA 75%配额', fusion_variance75_k50: '方差 75%配额',
  intersection_k50: '交集特征', union_k50: '并集特征', anova_only_k50: '仅ANOVA特征',
  variance_only_k50: '仅高方差特征', anova_matched_union_k50: '等预算ANOVA并集',
  variance_matched_union_k50: '等预算方差并集', add_variance_10: 'ANOVA50 + 方差补充10',
  add_variance_20: 'ANOVA50 + 方差补充20', add_variance_30: 'ANOVA50 + 方差补充30',
};

function chartNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function FusionPage() {
  const result = useApi<FusionData>('/api/v1/fusion/summary');
  const data = result.envelope?.data;
  const perf = data?.fusion_performance ?? [];
  const fusionOption = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: 'axis', valueFormatter: (value) => `${(Number(value) * 100).toFixed(2)}%` },
    grid: { left: 60, right: 22, top: 28, bottom: 90 },
    xAxis: { type: 'category', data: perf.map((row) => SCHEME_NAMES[String(row.scheme)] ?? String(row.scheme)), axisLabel: { rotate: 28, interval: 0, fontSize: 9 } },
    yAxis: { type: 'value', min: 0.94, max: 1.005, axisLabel: { formatter: (value) => `${(Number(value) * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: PALETTE.grid } } },
    series: [{ type: 'bar', barMaxWidth: 26, data: perf.map((row) => ({ value: chartNumber(row.validation_macro_f1_mean), itemStyle: { color: String(row.scheme).startsWith('anova') ? PALETTE.blue : String(row.scheme).startsWith('variance') ? PALETTE.teal : PALETTE.amber, borderRadius: [4, 4, 0, 0] } })) }],
  }), [perf]);

  const overlap = data?.feature_overlap ?? [];
  const overlapOption: EChartsOption = {
    tooltip: { trigger: 'axis' }, legend: { top: 2, data: ['平均交集', '平均并集'] }, grid: { left: 45, right: 18, top: 38, bottom: 32 },
    xAxis: { type: 'category', data: overlap.map((row) => `K=${row.k}`) }, yAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: PALETTE.grid } } },
    series: [{ name: '平均交集', type: 'bar', data: overlap.map((row) => chartNumber(row.intersection_mean)) }, { name: '平均并集', type: 'bar', data: overlap.map((row) => chartNumber(row.union_mean)) }],
  };
  const perfColumns = [
    { title: '方案', dataIndex: 'scheme', render: (value: string) => SCHEME_NAMES[value] ?? value },
    { title: '特征数K', dataIndex: 'k' }, { title: '实际平均特征数', dataIndex: 'n_features_mean', render: (value: number) => Number(value).toFixed(1) },
    { title: '开发集 Macro-F1', dataIndex: 'validation_macro_f1_mean', render: (value: number) => `${(Number(value) * 100).toFixed(3)}%` },
    { title: 'Balanced Acc.', dataIndex: 'validation_balanced_accuracy_mean', render: (value: number) => `${(Number(value) * 100).toFixed(3)}%` },
  ];
  const votingRows = data?.hard_voting ?? [];
  const arbitrationRows = data?.dynamic_arbitration ?? [];
  const pairedColumns = [
    { title: '比较方案', dataIndex: 'target', render: (value: string) => SCHEME_NAMES[value] ?? value },
    { title: '参照方案', dataIndex: 'reference', render: (value: string) => SCHEME_NAMES[value] ?? value },
    { title: '配对折数', dataIndex: 'n_paired_folds' },
    { title: 'Macro-F1差值', dataIndex: 'delta_macro_f1_mean', render: (value: number) => `${(Number(value) * 100).toFixed(3)} 个百分点` },
    { title: '纠错事件', dataIndex: 'n_rescued_predictions' }, { title: '新增错误', dataIndex: 'n_new_error_predictions' },
  ];

  return <div className="page-stack">
    <PageHeading eyebrow="FEATURE FUSION & ENSEMBLES" title="特征融合与消融" description="对照等预算融合、特征集合交并、三模型硬投票与动态仲裁的既有开发集实验。" extra={<Tag color="purple">开发集探索性扩展</Tag>} />
    <Alert type="warning" title="比较边界" content={data?.interpretation_note ?? '不同特征集合均能分类不等于已经证明信息互补；重复OOF事件也不代表独立患者。'} />
    <Grid.Row gutter={[16, 16]}>
      <Grid.Col xs={24} xl={15}><ChartPanel title="Top50预算下的融合方案" subtitle="展示每种真实记录方案的验证 Macro-F1；标签缩写映射到结果表中的配置。" option={fusionOption} loading={result.loading} error={result.error} status={result.envelope?.status} empty={!perf.length} height={370} /></Grid.Col>
      <Grid.Col xs={24} xl={9}><ChartPanel title="ANOVA 与方差集合重合" subtitle="同K共享训练折的平均基因交集与并集。" option={overlapOption} loading={result.loading} error={result.error} status={result.envelope?.status} empty={!overlap.length} height={370} /></Grid.Col>
    </Grid.Row>
    <Card className="panel-card" bordered={false} title={<div><div className="panel-title">特征融合性能与预算</div><div className="panel-subtitle">开发集重复交叉验证；相关验证折仅作描述性汇总</div></div>}>
      <RemotePanel loading={result.loading} error={result.error} status={result.envelope?.status} empty={!perf.length}><Table rowKey="scheme" columns={perfColumns} data={perf} pagination={{ pageSize: 8 }} /></RemotePanel>
      <SourceNote source={result.envelope?.source} note={data?.event_note} />
    </Card>
    <Grid.Row gutter={[16, 16]}>
      <Grid.Col xs={24} xl={12}><Card className="panel-card" bordered={false} title={<div><div className="panel-title">相同划分的配对差异</div><div className="panel-subtitle">仅展示已有的描述统计，不作独立样本显著性检验</div></div>}>
        <RemotePanel loading={result.loading} error={result.error} status={result.envelope?.status} empty={!data?.paired_comparisons.length}><Table rowKey={(row) => `${row.target}-${row.reference}`} columns={pairedColumns} data={data?.paired_comparisons ?? []} pagination={{ pageSize: 6 }} /></RemotePanel>
      </Card></Grid.Col>
      <Grid.Col xs={24} xl={12}><Card className="panel-card" bordered={false} title={<div><div className="panel-title">硬投票与动态仲裁</div><div className="panel-subtitle">直接读取既有实验汇总</div></div>}>
        <RemotePanel loading={result.loading} error={result.error} status={result.envelope?.status} empty={!votingRows.length && !arbitrationRows.length}>
          <div className="ensemble-summary">{votingRows.map((row, index) => <div className="ensemble-row" key={String(row['方案'] ?? index)}><strong>{String(row['方案'] ?? '硬投票')}</strong><span>Macro-F1 {typeof row['100折Macro-F1均值'] === 'number' ? (Number(row['100折Macro-F1均值']) * 100).toFixed(3) + '%' : '—'}</span><span>BA {typeof row['Balanced Accuracy均值'] === 'number' ? (Number(row['Balanced Accuracy均值']) * 100).toFixed(3) + '%' : '—'}</span></div>)}</div>
          <div className="arbitration-list">{arbitrationRows.slice(0, 6).map((row, index) => <div className="ensemble-row" key={String(row['方案'] ?? index)}><strong>{String(row['方案'] ?? '动态仲裁')}</strong><span>Macro-F1 {typeof row['100折Macro-F1均值'] === 'number' ? (Number(row['100折Macro-F1均值']) * 100).toFixed(3) + '%' : '—'}</span><span>BA {typeof row['100折Balanced Accuracy均值'] === 'number' ? (Number(row['100折Balanced Accuracy均值']) * 100).toFixed(3) + '%' : '—'}</span></div>)}</div>
        </RemotePanel>
      </Card></Grid.Col>
    </Grid.Row>
    <Alert type="info" title="额外成本与解释" content="融合方案实际使用的独立基因数可能高于单一Top-K；硬投票不输出患癌概率；动态仲裁源于既有开发集探索结果，不能作为独立验证成绩。" />
  </div>;
}

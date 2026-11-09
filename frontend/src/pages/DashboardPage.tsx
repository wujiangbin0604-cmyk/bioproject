import { useMemo } from 'react';
import { Button, Card, Grid, Tag } from '@arco-design/web-react';
import { useNavigate } from 'react-router-dom';
import type { EChartsOption } from 'echarts';
import { useApi } from '../hooks';
import type { ExperimentStatus, ModelComparisonData } from '../types/api';
import { MetricCard } from '../components/MetricCard';
import { ChartPanel } from '../components/ChartPanel';
import { RemotePanel, SourceNote } from '../components/RemotePanel';
import { PALETTE } from '../constants';

export function DashboardPage() {
  const navigate = useNavigate();
  const comparisons = useApi<ModelComparisonData>('/api/v1/models/comparison');
  const status = useApi<ExperimentStatus>('/api/v1/experiments/status');
  const m1 = comparisons.envelope?.data.models.find((item) => item.model === 'M1');
  const chartOption = useMemo<EChartsOption>(() => {
    const models = comparisons.envelope?.data.models ?? [];
    return {
      color: [PALETTE.blue, PALETTE.teal],
      tooltip: { trigger: 'axis', valueFormatter: (value) => `${(Number(value) * 100).toFixed(2)}%` },
      legend: { top: 2, right: 12, data: ['开发集 100 折均值', '回顾性保留集'] },
      grid: { left: 50, right: 22, top: 42, bottom: 32 },
      xAxis: { type: 'category', data: models.map((item) => String(item.model)), axisTick: { show: false } },
      yAxis: { type: 'value', min: 0.94, max: 1.005, axisLabel: { formatter: (value) => `${(Number(value) * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: '#E8EEF0' } } },
      series: [
        { name: '开发集 100 折均值', type: 'line', smooth: 0.22, symbolSize: 8, data: models.map((item) => item.development_macro_f1_100fold_mean), lineStyle: { width: 2 } },
        { name: '回顾性保留集', type: 'line', smooth: 0.22, symbolSize: 8, data: models.map((item) => item.macro_f1), lineStyle: { width: 2 }, markPoint: { data: [{ type: 'max', name: '最高' }] } },
      ],
    };
  }, [comparisons.envelope]);

  const steps = [
    { title: '数据质量检查', route: '/dataset', mark: '01' }, { title: '固定数据划分', route: '/dataset', mark: '02' },
    { title: '特征筛选', route: '/features', mark: '03' }, { title: '分类模型', route: '/models', mark: '04' },
    { title: '稳定性与融合', route: '/fusion', mark: '05' }, { title: '回顾性评价', route: '/models', mark: '06' },
  ];
  const statusItems = status.envelope?.data.experiments ?? [];

  return <div className="page-stack">
    <div className="hero-panel">
      <div className="hero-copy"><div className="hero-kicker"><span className="hero-kicker-dot" /> RNA-SEQ · FEATURE ANALYSIS · CLASSIFICATION</div>
        <h1>基于 RNA-Seq 的高维基因表达<br />特征选择与癌症分类</h1>
        <p>在 20,531 维表达空间中探索特征筛选、选择稳定性与五类肿瘤表达分类表现。</p>
        <div className="hero-tags"><Tag>UCI Dataset 401</Tag><Tag>640 开发样本</Tag><Tag>固定随机种子 42</Tag></div>
        <Button type="primary" className="hero-button" onClick={() => navigate('/lab')}>进入交互式模型实验室 <span>→</span></Button>
      </div>
      <div className="hero-art" aria-hidden="true"><div className="art-grid" /><div className="art-ring ring-one" /><div className="art-ring ring-two" /><div className="art-core">RNA<br /><span>SEQ</span></div><span className="art-label label-a">20,531 features</span><span className="art-label label-b">5 tumor classes</span><span className="art-label label-c">M1 · ANOVA50</span></div>
    </div>

    <div className="metric-grid five">
      <MetricCard label="肿瘤样本" value="801" detail="五类已患癌样本" accent="blue" />
      <MetricCard label="表达特征" value="20,531" detail="原始匿名 gene_* 列" accent="teal" />
      <MetricCard label="癌种类别" value="05" detail="BRCA · KIRC · COAD · LUAD · PRAD" accent="amber" />
      <MetricCard label="开发集" value="640" detail="重复交叉验证与开发分析" accent="ink" />
      <MetricCard label="保留集" value="161" detail="同源数据的回顾性评价" accent="teal" />
    </div>

    <div className="section-row"><div><div className="eyebrow">RESEARCH PIPELINE</div><h2>研究工作流程</h2></div><span className="muted-inline">点击阶段进入对应结果页</span></div>
    <div className="workflow-strip">{steps.map((step, index) => <button className="workflow-step" key={step.mark} onClick={() => navigate(step.route)}>
      <span className="workflow-mark">{step.mark}</span><strong>{step.title}</strong>{index < steps.length - 1 && <span className="workflow-arrow">→</span>}
    </button>)}</div>

    <Grid.Row gutter={[16, 16]}>
      <Grid.Col xs={24} xl={15}>
        <ChartPanel title="M0–M5 Macro-F1 概览" subtitle="开发集100折均值与回顾性保留集指标。" option={chartOption} loading={comparisons.loading} error={comparisons.error} status={comparisons.envelope?.status} empty={!comparisons.envelope?.data.models.length} height={330} />
        <SourceNote source={comparisons.envelope?.source} />
      </Grid.Col>
      <Grid.Col xs={24} xl={9}>
        <Card className="panel-card health-card" bordered={false} title={<div><div className="panel-title">研究记录状态</div><div className="panel-subtitle">检查已保存的汇总文件</div></div>}>
          <RemotePanel loading={status.loading} error={status.error} status={status.envelope?.status}>
            <div className="status-list">{statusItems.map((item) => <div className="status-row" key={item.id}><span className={`status-indicator status-${item.status}`} /><span>{item.name}</span><Tag color={item.status === 'available' ? 'green' : item.status === 'invalid' ? 'red' : 'gray'}>{item.status === 'available' ? '已载入' : item.status === 'invalid' ? '格式异常' : '未导入'}</Tag></div>)}</div>
          </RemotePanel>

        </Card>
      </Grid.Col>
    </Grid.Row>

    <div className="metric-grid two">
      <MetricCard label="M1 开发集 Macro-F1" value={typeof m1?.development_macro_f1_100fold_mean === 'number' ? (Number(m1.development_macro_f1_100fold_mean) * 100).toFixed(3) + '%' : '—'} detail="ANOVA Top50 + LinearSVC · 100个相关验证折" accent="blue" />
      <MetricCard label="M1 回顾性保留集 Macro-F1" value={typeof m1?.macro_f1 === 'number' ? (Number(m1.macro_f1) * 100).toFixed(3) + '%' : '—'} detail="161例保留集" accent="amber" />
    </div>
  </div>;
}

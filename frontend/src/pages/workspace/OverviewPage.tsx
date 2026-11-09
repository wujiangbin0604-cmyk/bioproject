import { useMemo } from 'react';
import { Button } from '@arco-design/web-react';
import { Link } from 'react-router-dom';
import type { Dataset, Results } from '../../api/platform';
import { terminal } from '../../api/platform';
import type { DatasetSummary, Envelope } from '../../types/api';
import { useWorkspace } from '../../hooks/useWorkspace';
import { useLiveResource } from '../../hooks/useLiveResource';
import { usePreferences } from '../../hooks/usePreferences';
import { Icon } from '../../components/ui/Icon';
import { ErrorState } from '../../components/ui/States';
import { ChallengeEntryCard, SummaryCard, WorkflowCard } from '../../components/dashboard/DashboardCards';
import { DistributionCard, SplitDistributionCard } from '../../components/dashboard/DistributionCards';
import { PerformanceTable } from '../../components/dashboard/PerformanceTable';
import { ExplorationCard } from '../../components/dashboard/ExplorationCard';
import { RecentExperimentsTable } from '../../components/dashboard/RecentExperimentsTable';
import { formatCount } from '../../utils/dashboard';

export default function OverviewPage() {
  const { datasets, tasks, models, datasetId } = useWorkspace();
  const { settings } = usePreferences();
  const current = datasets.data?.items.find(item => item.dataset_id === datasetId);
  const summary = useLiveResource<Dataset>(current?.status === 'ready' ? `/api/v1/datasets/${datasetId}/summary` : null);
  const study = useLiveResource<Envelope<DatasetSummary>>(datasetId === 'pancan' ? '/api/v1/dataset/summary' : null);
  const datasetTasks = useMemo(() => (tasks.data?.items ?? []).filter(task => task.dataset_id === datasetId).sort((a, b) => b.created_at.localeCompare(a.created_at)), [tasks.data, datasetId]);
  const completed = useMemo(() => datasetTasks.filter(task => task.status === 'completed').slice(0, 8), [datasetTasks]);
  const ids = completed.map(task => task.task_id).join(',');
  const comparisons = useLiveResource<{ items: Results[] }>(ids ? `/api/v1/comparison?task_ids=${encodeURIComponent(ids)}` : null);
  const rows = useMemo(() => comparisons.data?.items.filter(item => item.dataset_id === datasetId).flatMap(item => item.results.map(result => ({ ...result, config: item.configuration, task: item.task_id }))) ?? [], [comparisons.data, datasetId]);
  const running = tasks.data?.items.filter(task => !terminal(task.status));
  const chartLoading = datasets.loading || summary.loading;

  return <div className="workspace-page research-dashboard">
    <div className="dashboard-page-heading"><div><div className="dashboard-title-line"><Icon name="grid" size={25} /><h1>项目总览</h1><span>Project Overview / Dashboard</span></div><p>项目整体运行情况、数据统计、模型效果与研究流程概览</p></div><Link to="/lab"><Button type="primary"><Icon name="flask" size={15} /> 创建实验</Button></Link></div>
    <ErrorState message={datasets.error || tasks.error || models.error} />
    <ChallengeEntryCard />
    <div className="dashboard-summary-grid">
      <SummaryCard label="已注册数据集" value={datasets.data?.items.length} detail={`${datasets.data?.items.filter(item => item.status === 'ready').length ?? '—'} 个已就绪 · 官方来源与独立版本`} icon="database" tone="blue" to="/datasets" loading={datasets.loading} />
      <SummaryCard label="当前数据集样本" value={current?.samples} detail={`${formatCount(current?.features)} 个表达特征 · ${datasetId.toUpperCase()}`} icon="dna" tone="cyan" to={`/datasets?dataset=${datasetId}`} loading={datasets.loading} />
      <SummaryCard label="已注册模型" value={models.data?.items.length} detail="可信训练流程 · 数据集版本绑定" icon="features" tone="purple" to="/predict" loading={models.loading} />
      <SummaryCard label="运行中的实验" value={tasks.data ? running?.length : undefined} detail={`${formatCount(tasks.data?.items.length)} 次实验 · 实时追踪训练状态`} icon="monitor" tone="mint" to="/monitor" loading={tasks.loading} />
    </div>
    <div className="dashboard-section-caption"><span><i /> 数据分析看板</span><span>{datasetId.toUpperCase()}<b />{current?.status === 'ready' ? '已导入数据' : '待导入数据'}<b />每 {settings.pollSeconds} 秒刷新实验状态</span></div>
    <div className="dashboard-chart-grid">
      <PerformanceTable rows={rows} datasetId={datasetId} loading={tasks.loading || comparisons.loading} error={comparisons.error} />
      <DistributionCard dataset={current} loading={datasets.loading} />
      <SplitDistributionCard task={datasetTasks.find(task => task.folds?.some(fold => fold.train_samples != null && fold.validation_samples != null))} study={study.data?.status === 'available' || study.data?.status === 'partial' ? study.data.data : undefined} loading={tasks.loading || study.loading} error={study.error} />
    </div>
    <div className="dashboard-detail-grid">
      <ExplorationCard dataset={summary.data ?? current} rows={rows} loading={chartLoading || comparisons.loading} error={summary.error} />
      <RecentExperimentsTable tasks={datasetTasks} datasets={datasets.data?.items ?? []} loading={tasks.loading} error={tasks.error} />
    </div>
    <WorkflowCard />
    <p className="dashboard-research-note"><Link to="/research">查看原研究档案</Link></p>
  </div>;
}

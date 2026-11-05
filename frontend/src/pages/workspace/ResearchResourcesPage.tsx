import { Link } from 'react-router-dom';
import type { Dataset } from '../../api/platform';
import { useWorkspace } from '../../hooks/useWorkspace';
import { useLiveResource } from '../../hooks/useLiveResource';
import { HeatmapExplorer } from '../../components/charts/HeatmapExplorer';
import { DistributionCard } from '../../components/dashboard/DistributionCards';
import { WorkflowCard } from '../../components/dashboard/DashboardCards';
import { GlassCard } from '../../components/ui/GlassCard';
import { PageTitle } from '../../components/ui/PageTitle';
import { ErrorState, LoadingSkeleton } from '../../components/ui/States';
import { UserFlowGuide } from '../../components/onboarding/UserFlowGuide';
import { Icon } from '../../components/ui/Icon';

export function GalleryPage() {
  const { datasetId, datasets } = useWorkspace();
  const current = datasets.data?.items.find(item => item.dataset_id === datasetId);
  const summary = useLiveResource<Dataset>(current?.status === 'ready' ? `/api/v1/datasets/${datasetId}/summary` : null);
  return <div className="workspace-page"><PageTitle icon="grid" title="科研可视化图库" description={`探索 ${datasetId.toUpperCase()} 的真实表达模式与类别分布，可通过顶部切换数据集。`} />
    <ErrorState message={datasets.error || summary.error} /><div className="gallery-grid"><GlassCard title={<><Icon name="features" /> 基因表达热图</>} subtitle="真实表达矩阵 · 支持视图切换与图表导出">{summary.loading ? <LoadingSkeleton rows={7} /> : <HeatmapExplorer key={datasetId} data={summary.data?.heatmap} />}</GlassCard><DistributionCard dataset={current} loading={datasets.loading} /></div>
    <div className="research-resource-links"><Link to={`/features?dataset=${datasetId}`}><Icon name="features" /> 特征排名与稳定性分析 <Icon name="arrow" size={15} /></Link><Link to="/comparison"><Icon name="compare" /> 模型性能与混淆矩阵 <Icon name="arrow" size={15} /></Link></div>
  </div>;
}

export function PresentationPage() {
  return <div className="workspace-page"><PageTitle icon="play" title="课程答辩演示" description="从教学热图到真实实验，按研究流程演示平台功能。" />
    <UserFlowGuide autoOpenOnFirstVisit={false} title="从互动学习开始" />
    <WorkflowCard />
    <GlassCard title={<><Icon name="dna" /> 研究演示资料</>} subtitle="原 PANCAN 研究结果与平台分析功能"><div className="research-resource-links"><Link to="/research">原研究总览 <Icon name="arrow" size={15} /></Link><Link to="/models">M0–M5 回顾性评价 <Icon name="arrow" size={15} /></Link><Link to="/research/features">特征选择与稳定性 <Icon name="arrow" size={15} /></Link><Link to="/about">数据来源与研究范围 <Icon name="arrow" size={15} /></Link></div></GlassCard>
  </div>;
}

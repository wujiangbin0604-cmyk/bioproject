import { useMemo, useState } from 'react';
import { Button, Progress, Select, Space, Tabs } from '@arco-design/web-react';
import { Link, useNavigate } from 'react-router-dom';
import type { Dataset, Model, Results, Task } from '../../api/platform';
import { names, number, terminal } from '../../api/platform';
import { useLiveResource } from '../../hooks/useLiveResource';
import { usePreferences } from '../../hooks/usePreferences';
import { GlassCard } from '../../components/ui/GlassCard';
import { AnimatedStat } from '../../components/ui/AnimatedStat';
import { GradientButton } from '../../components/ui/GradientButton';
import { Crossfade } from '../../components/ui/Crossfade';
import { Icon } from '../../components/ui/Icon';
import type { IconName } from '../../components/ui/Icon';
import { HeroDNA } from '../../components/visuals/AnimatedDNA';
import { ErrorState, EmptyState, LoadingSkeleton } from '../../components/ui/States';
import { ExperimentStatus } from '../../components/ui/ExperimentStatus';
import { TaskTable } from '../../components/experiments/TaskTable';
import { HeatmapExplorer } from '../../components/charts/HeatmapExplorer';
import { OverviewAnalysisChart } from '../../components/charts/OverviewAnalysisChart';
import { datasetNames } from '../../utils/platform';

const shortcuts: { title: string; hint: string; icon: IconName; path: string; tone: string }[] = [
  { title: '导入数据集', hint: '官方矩阵 / 本地上传', icon: 'upload', path: '/datasets', tone: 'blue' },
  { title: '创建实验', hint: '配置算法与特征', icon: 'flask', path: '/lab', tone: 'purple' },
  { title: '训练模型', hint: '共享划分 / 真实CV', icon: 'features', path: '/lab?step=1', tone: 'cyan' },
  { title: '模型预测', hint: '验证单样本表达', icon: 'target', path: '/predict', tone: 'mint' },
];

export default function OverviewPage() {
  const navigate = useNavigate(), { settings } = usePreferences();
  const [dataset, setDataset] = useState('pancan'), [tab, setTab] = useState('performance');
  const datasets = useLiveResource<{ items: Dataset[] }>('/api/v1/datasets', { interval: settings.pollSeconds * 1000 });
  const tasks = useLiveResource<{ items: Task[] }>('/api/v1/experiments', { interval: settings.pollSeconds * 1000 });
  const models = useLiveResource<{ items: Model[] }>('/api/v1/models', { interval: settings.pollSeconds * 1000 });
  const summary = useLiveResource<Dataset>(`/api/v1/datasets/${dataset}/summary`);
  const items = useMemo(() => tasks.data?.items ?? [], [tasks.data]);
  const running = useMemo(() => items.filter(task => !terminal(task.status)), [items]);
  const completed = useMemo(() => items.filter(task => task.status === 'completed' && task.dataset_id === dataset).slice(0, 8), [items, dataset]);
  const ids = completed.map(task => task.task_id).join(',');
  const comparisons = useLiveResource<{ items: Results[] }>(ids ? `/api/v1/comparison?task_ids=${ids}` : null);
  const rows = useMemo(() => comparisons.data?.items.flatMap(task => task.results.map(result => ({ ...result, config: task.configuration, task: task.task_id }))) ?? [], [comparisons.data]);
  const latest = rows[0], currentDataset = datasets.data?.items.find(item => item.dataset_id === dataset);
  const chartAvailable = tab === 'distribution' ? !!currentDataset?.classes : rows.length > 0;

  return <div className="workspace-page overview-page">
    <ErrorState message={datasets.error || tasks.error || models.error} />
    <section className="welcome-hero">
      <div className="welcome-copy">
        <div className="welcome-heading">
          <span className="welcome-dna-icon"><Icon name="dna" size={32} /></span>
          <div><h1>欢迎使用 GeneScope 2.0</h1><p>从基因数据到生物学洞察，构建可复现的机器学习分析流程</p></div>
        </div>
        <div className="hero-protocols">
          <span><Icon name="check" size={14} /> 多数据集</span>
          <span><Icon name="check" size={14} /> 训练折内 Pipeline</span>
          <span><Icon name="check" size={14} /> 真实任务监控</span>
        </div>
      </div>
      <HeroDNA />
    </section>

    <div className="overview-stats">
      <AnimatedStat label="已就绪数据集" value={datasets.data?.items.filter(item => item.status === 'ready').length} detail="官方来源 · 独立版本" icon="database" tone="blue" to="/datasets" />
      <AnimatedStat label="实验总数" value={tasks.data?.items.length} detail="完整配置 · 历史可追溯" icon="flask" tone="purple" index={1} to="/experiments" />
      <AnimatedStat label="已注册模型" value={models.data?.items.length} detail="可信训练流程生成" icon="features" tone="cyan" index={2} to="/predict" />
      <AnimatedStat label="正在运行的实验" value={tasks.data ? running.length : undefined} detail="实时任务状态" icon="target" tone="mint" index={3} to="/monitor" />
    </div>

    <div className="overview-launch-row">
      <GlassCard title={<><Icon name="upload" /> 快速启动</>} className="quick-start-panel">
        <div className="quick-start-grid">{shortcuts.map(shortcut =>
          <button key={shortcut.title} className={`quick-start tone-${shortcut.tone}`} onClick={() => navigate(shortcut.path)}>
            <Icon name={shortcut.icon} size={34} /><strong>{shortcut.title}</strong><small>{shortcut.hint}</small>
            <Icon name="arrow" size={15} className="quick-start-arrow" />
          </button>)}</div>
      </GlassCard>
      <GlassCard title={<><Icon name="monitor" /> 任务概览 <span className="heading-count">运行中 {running.length}</span></>}
        extra={<Link to="/monitor" className="quiet-link">查看全部 <Icon name="chevron" size={13} /></Link>}>
        <div className="task-overview-list">{(running.length ? running.slice(0, 3) : items.slice(0, 3)).map(task =>
          <button key={task.task_id} onClick={() => navigate(`/monitor/${task.task_id}`)} aria-label={`查看任务 ${task.task_id}`}>
            <span className="task-mini-icon"><Icon name="flask" size={17} /></span>
            <span className="task-mini-description">
              <strong title={task.experiment_config.algorithms?.map(algorithm => names[algorithm]).join(' / ')}>{task.experiment_config.algorithms?.map(algorithm => names[algorithm]).join(' / ') || '分类实验'}</strong>
              <small>{datasetNames[task.dataset_id]} · {task.task_id.slice(0, 6)}</small>
            </span>
            {!terminal(task.status) && <span className="task-mini-progress"><Progress percent={task.progress} size="small" color="#38c6a5" /></span>}
            <ExperimentStatus status={task.status} compact /><Icon className="task-mini-chevron" name="chevron" size={13} />
          </button>)}
          {!items.length && <EmptyState title="尚无实验任务" action={<Button type="text" onClick={() => navigate('/lab')}>创建第一个实验</Button>} />}
        </div>
      </GlassCard>
    </div>

    <div className="overview-analysis-row">
      <GlassCard className="overview-chart-panel" title={<><Icon name="compare" /> 真实实验分析</>}
        extra={<Select aria-label="总览分析数据集" size="small" value={dataset} onChange={setDataset} style={{ width: 178 }}
          options={(datasets.data?.items ?? []).map(item => ({ value: item.dataset_id, label: datasetNames[item.dataset_id] }))} />}>
        <Tabs activeTab={tab} onChange={setTab} type="rounded" size="small" className="analysis-tabs">
          {[['performance', '分类性能'], ['features', '特征选择'], ['distribution', '数据分布']].map(([key, title]) => <Tabs.TabPane key={key} title={title} />)}
        </Tabs>
        <Crossfade key={dataset} identity={tab}>
          {comparisons.loading && tab !== 'distribution' ? <LoadingSkeleton rows={5} /> : chartAvailable ?
            <OverviewAnalysisChart tab={tab} rows={rows} latestTaskId={completed[0]?.task_id} dataset={currentDataset} /> :
            <EmptyState title="尚无已完成的实验结果" action={<Button onClick={() => navigate('/lab')}>创建实验</Button>} />}
          <p className="small-note chart-source-note">{tab === 'distribution' ? '纳入样本的实际类别分布' : tab === 'features' ? 'CV训练折集合的平均Jaccard；各实验保留独立配置' : '最近完成实验的共享划分CV均值 · 仅开发数据'} · {datasetNames[dataset]}</p>
        </Crossfade>
        <ErrorState message={comparisons.error} />
      </GlassCard>
      <GlassCard title={<><Icon name="target" /> 最近实验快照</>} className="snapshot-panel">
        {latest ? <>
          <span className="snapshot-dataset">{datasetNames[dataset]}</span><h3>{names[latest.algorithm]}</h3>
          <span className="small-note">{names[latest.config.selection]} / K={latest.config.selection === 'none' ? '全部' : latest.config.k}</span>
          <div className="snapshot-metrics">
            <div className="tone-mint"><span>CV Macro-F1</span><strong>{number(latest.metrics.macro_f1.mean)}</strong><small>± {number(latest.metrics.macro_f1.std)}</small></div>
            <div className="tone-purple"><span>特征稳定性</span><strong>{number(latest.jaccard_mean)}</strong><small>平均 Jaccard</small></div>
          </div>
          <dl className="snapshot-details">
            <div><dt>实际特征数</dt><dd>{latest.n_features.toLocaleString()}</dd></div>
            <div><dt>CV耗时</dt><dd>{number(latest.fit_seconds, 2)}s</dd></div>
            <div><dt>评价协议</dt><dd>{latest.config.folds}折 × {latest.config.repeats}轮</dd></div>
          </dl>
          <GradientButton long onClick={() => navigate(`/monitor/${latest.task}`)}>查看完整实验结果 <Icon name="arrow" size={15} /></GradientButton>
        </> : <EmptyState title="尚无实验快照" description="完成实验后显示真实评价结果" />}
      </GlassCard>
    </div>

    <div className="overview-bottom-row">
      <GlassCard title={<><Icon name="features" /> 基因表达热图</>} extra={<Link to={`/features?dataset=${dataset}`} className="quiet-link">特征分析 <Icon name="chevron" size={13} /></Link>}>
        {summary.loading ? <LoadingSkeleton rows={5} /> : <HeatmapExplorer data={summary.data?.heatmap} compact />}<ErrorState message={summary.error} />
      </GlassCard>
      <GlassCard title={<><Icon name="history" /> 最近实验记录</>} extra={<Link to="/experiments" className="quiet-link">查看全部 <Icon name="chevron" size={13} /></Link>}>
        <TaskTable tasks={items.slice(0, 5)} compact loading={tasks.loading} />
      </GlassCard>
    </div>
    <div className="platform-capabilities"><Space wrap size={18}>
      <span><Icon name="check" size={14} /> 独立数据协议</span><span><Icon name="check" size={14} /> 患者分组隔离</span>
      <span><Icon name="check" size={14} /> 特征清单校验</span><Link to="/research">查看原PANCAN研究档案 <Icon name="arrow" size={13} /></Link>
    </Space></div>
  </div>;
}

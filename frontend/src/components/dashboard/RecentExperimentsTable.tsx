import { Link } from 'react-router-dom';
import type { Dataset, Task } from '../../api/platform';
import { names } from '../../api/platform';
import { GlassCard } from '../ui/GlassCard';
import { Icon } from '../ui/Icon';
import { ExperimentStatus } from '../ui/ExperimentStatus';
import { EmptyState, ErrorState, LoadingSkeleton } from '../ui/States';

export function RecentExperimentsTable({ tasks, datasets, loading, error }: { tasks: Task[]; datasets: Dataset[]; loading: boolean; error?: string }) {
  return <GlassCard className="dashboard-recent" title={<><Icon name="history" /> 最近实验记录</>} subtitle="Recent Experiments" extra={<Link to="/experiments" className="quiet-link">查看全部 <Icon name="chevron" size={12} /></Link>}>
    <ErrorState message={error} />{loading ? <LoadingSkeleton rows={5} /> : tasks.length ? <div className="dashboard-table-scroll"><table className="recent-table"><thead><tr><th>实验名称</th><th>数据集</th><th>模型</th><th>状态</th><th>创建时间</th></tr></thead><tbody>{tasks.slice(0, 5).map(task => <tr key={task.task_id}>
      <td><Link to={`/monitor/${task.task_id}`} className="experiment-name"><span className="experiment-table-icon"><Icon name="flask" size={15} /></span><span>{names[task.experiment_config.selection] ?? '分类实验'}<small>{task.task_id.slice(0, 10)} · K={task.experiment_config.selection === 'none' ? '全部' : task.experiment_config.k}</small></span></Link></td>
      <td title={datasets.find(d => d.dataset_id === task.dataset_id)?.name}>{task.dataset_id.toUpperCase()}</td><td className="recent-models" title={task.experiment_config.algorithms.map(a => names[a] ?? a).join(' / ')}>{task.experiment_config.algorithms.map(a => names[a] ?? a).join(' / ')}</td><td><ExperimentStatus status={task.status} compact /></td>
      <td><time dateTime={task.created_at}>{new Date(task.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })}</time></td>
    </tr>)}</tbody></table></div> : <EmptyState title="当前数据集尚无实验记录" description="配置模型与特征选择方案，开始一次可追溯的实验" action={<Link to="/lab">创建第一个实验</Link>} />}
    <div className="recent-footer"><span><Icon name="info" size={13} /> 随当前数据集筛选 · 自动刷新</span><Link to="/monitor">查看实时监控 <Icon name="arrow" size={12} /></Link></div>
  </GlassCard>;
}

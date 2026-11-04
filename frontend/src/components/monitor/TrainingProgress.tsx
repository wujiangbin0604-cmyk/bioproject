import { Progress, Tooltip } from '@arco-design/web-react';
import type { Task } from '../../api/platform';
import { number } from '../../api/platform';
import { taskStages } from '../../utils/taskStages';
import { Icon } from '../ui/Icon';
import { ExperimentStatus } from '../ui/ExperimentStatus';
export function TrainingProgress({ task, elapsed }: { task: Task; elapsed: number }) {
  const stages = taskStages(task);
  return <div className="training-progress"><div className="training-stage-heading"><div><ExperimentStatus status={task.status} /><h2>{task.current_stage}</h2></div><span className="elapsed-clock">{number(elapsed, 1)}<small>已用时间 / 秒</small></span></div><Progress percent={task.progress} showText={false} color={{ '0%': '#5598ff', '65%': '#8b8bfa', '100%': '#37d4b1' }} status={task.status === 'failed' ? 'error' : 'normal'} /><div className="progress-caption"><span>已完成 {task.completed_folds} / {task.total_folds} 折</span><strong>{task.progress}%</strong></div>{task.kind !== 'import' && <><div className="training-timeline">{['数据准备', '特征选择', '模型训练', '模型评价', '结果生成'].map((title, i) => <Tooltip key={title} content={i > 0 && i < 4 ? 'CV期间为同一折内流程；后端提供折级进度，未提供单步骤耗时' : title}><div className={`training-node node-${stages[i]}`}><span>{stages[i] === 'complete' ? <Icon name="check" size={18} /> : <Icon name={(['database', 'features', 'flask', 'compare', 'target'] as const)[i]} size={20} />}</span><strong>{title}</strong><small>{stages[i] === 'complete' ? '已完成' : stages[i] === 'active' ? i > 0 && i < 4 ? '折内流程' : '运行中' : stages[i] === 'stopped' ? '已停止' : '未开始'}</small></div></Tooltip>)}</div><p className="small-note">特征选择、训练和评价在每个训练折内重复执行；时间线按真实折级事件显示。</p></>}</div>;
}

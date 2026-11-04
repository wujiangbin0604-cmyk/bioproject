import { useEffect, useState } from 'react';
import { Button, Checkbox, Descriptions, Message, Modal, Space, Table, Tabs, Tag } from '@arco-design/web-react';
import { useParams, useNavigate } from 'react-router-dom';
import type { Fold, Results, Task } from '../../api/platform';
import { names, terminal, downloadResult, number } from '../../api/platform';
import { api, getErrorMessage } from '../../api/client';
import { useTaskStream } from '../../hooks/useTaskStream';
import { useLiveResource } from '../../hooks/useLiveResource';
import { usePreferences } from '../../hooks/usePreferences';
import { GlassCard } from '../../components/ui/GlassCard';
import { PageTitle } from '../../components/ui/PageTitle';
import { GradientButton } from '../../components/ui/GradientButton';
import { Icon } from '../../components/ui/Icon';
import { ErrorState, EmptyState, LoadingSkeleton } from '../../components/ui/States';
import { TrainingProgress } from '../../components/monitor/TrainingProgress';
import { TrainingLogs } from '../../components/monitor/TrainingLogs';
import { RealTimeChart } from '../../components/charts/RealTimeChart';
import { ResultSummary } from '../../components/experiments/ResultSummary';
import { TaskTable } from '../../components/experiments/TaskTable';
import { datasetNames, metricNames, reportError, copyText } from '../../utils/platform';

export default function MonitoringPage() {
  const { taskId } = useParams(), navigate = useNavigate();
  const { task, error, connected } = useTaskStream(taskId);
  const [tick, setTick] = useState(Date.now()), [metrics, setMetrics] = useState(['macro_f1', 'balanced_accuracy', 'accuracy']), [chartMode, setChartMode] = useState('metrics'), [cancelBusy, setCancelBusy] = useState(false);
  const result = useLiveResource<Results>(task?.kind === 'experiment' && task.status === 'completed' ? `/api/v1/experiments/${taskId}/results` : null);
  useEffect(() => { if (!task || terminal(task.status)) return; const timer = setInterval(() => setTick(Date.now()), 1000); return () => clearInterval(timer); }, [task?.status]);
  const elapsed = task && !terminal(task.status) ? Math.max(task.elapsed_seconds, (tick - Date.parse(task.started_at ?? task.created_at)) / 1000) : task?.elapsed_seconds ?? 0;
  async function cancel() {
    if (!task) return;
    setCancelBusy(true);
    try { await api.post(`/api/v1/experiments/${task.task_id}/cancel`); Message.success('工作进程已收到取消请求'); }
    catch (e) { Message.error(getErrorMessage(e)); } finally { setCancelBusy(false); }
  }
  return <div className="workspace-page"><PageTitle icon="monitor" title={task?.kind === 'import' ? '数据集导入监控' : '实时训练监控'} description={taskId ? `任务 ${taskId}` : '正在载入任务'} extra={task && !terminal(task.status) ? <Button status="danger" loading={cancelBusy} disabled={task.status === 'cancel_requested'} onClick={() => Modal.confirm({ title: '停止当前计算？', content: '会停止真实工作进程，并保留已经完成的折结果。', onOk: cancel })}>取消任务</Button> : <Button onClick={() => navigate('/experiments')}>实验历史</Button>} />
    <ErrorState message={task?.error || error || result.error} />{!task ? <LoadingSkeleton rows={8} /> : <><GlassCard className="monitor-progress-card"><div className="monitor-source-row"><Tag color="arcoblue">{datasetNames[task.dataset_id] ?? task.dataset_id}</Tag><span className={`stream-state ${connected ? 'is-connected' : ''}`}><i />{terminal(task.status) ? '已读取保存结果' : connected ? '实时事件已连接' : '正在连接任务'}</span><Button type="text" size="mini" aria-label="复制任务ID" icon={<Icon name="copy" size={14} />} onClick={() => void copyText(task.task_id)} /></div><TrainingProgress task={task} elapsed={elapsed} /></GlassCard>
      <div className="monitor-main-grid"><GlassCard title={<><Icon name="compare" /> 逐折验证表现</>} extra={<span className="small-note">{task.completed_folds} 条真实折结果</span>}><div className="monitor-chart-controls"><Tabs type="rounded" size="small" activeTab={chartMode} onChange={setChartMode}><Tabs.TabPane key="metrics" title="评价指标" /><Tabs.TabPane key="time" title="计算耗时" /></Tabs>{chartMode === 'metrics' && <Checkbox.Group value={metrics} onChange={v => setMetrics(v.map(String))} options={['macro_f1', 'balanced_accuracy', 'accuracy'].map(v => ({ value: v, label: metricNames[v] }))} />}</div><div className="live-chart-area"><RealTimeChart folds={task.folds ?? []} metrics={metrics} time={chartMode === 'time'} />{!task.folds?.length && <div className="chart-empty-overlay"><EmptyState title={task.kind === 'import' ? '正在核验表达矩阵与元数据' : '等待第一折真实评价结果'} /></div>}</div></GlassCard>
        <GlassCard title={<><Icon name="flask" /> 实验配置</>}><Descriptions column={1} data={[{ label: '数据集', value: datasetNames[task.dataset_id] }, { label: '模型', value: task.experiment_config.algorithms?.map(a => names[a]).join(' / ') ?? '数据导入' }, { label: '特征方法', value: names[task.experiment_config.selection] ?? '官方矩阵适配器' }, { label: '特征数', value: task.experiment_config.selection === 'none' ? '全特征' : task.experiment_config.k ?? '—' }, { label: '评价轮次', value: task.total_folds ? `${task.experiment_config.folds}折 × ${task.experiment_config.repeats}轮` : '不适用' }, { label: '随机种子', value: task.experiment_config.seed ?? '—' }, { label: '开始时间', value: task.started_at ? new Date(task.started_at).toLocaleString() : '尚未开始' }]} /><Button type="text" onClick={() => void downloadResult(task.task_id, 'json').catch(reportError)}>下载完整配置与结果 <Icon name="download" size={14} /></Button></GlassCard></div>
      <GlassCard title={<><Icon name="list" /> 各折结果</>}><Table<Fold> rowKey={r => `${r.algorithm}_${r.repeat}_${r.fold}`} data={task.folds ?? []} scroll={{ x: 850 }} size="small" pagination={{ pageSize: 10, showTotal: true }} columns={[{ title: '模型', dataIndex: 'algorithm', render: a => names[a] }, { title: '轮次', dataIndex: 'repeat', width: 60 }, { title: '折', dataIndex: 'fold', width: 55 }, ...['macro_f1', 'balanced_accuracy', 'accuracy'].map(k => ({ title: metricNames[k], dataIndex: k, render: (n: number) => number(n) })), { title: '特征数', dataIndex: 'n_features' }, { title: '耗时(s)', dataIndex: 'fit_seconds', render: n => number(n, 3) }]} /></GlassCard>
      {result.data && <GlassCard title={<><Icon name="check" /> 最终汇总</>} extra={<Space><Button size="small" onClick={() => void downloadResult(task.task_id, 'csv').catch(reportError)}>CSV</Button><Button size="small" onClick={() => void downloadResult(task.task_id, 'json').catch(reportError)}>JSON</Button></Space>}><ResultSummary output={result.data} /><div className="result-next-actions"><GradientButton onClick={() => navigate(`/comparison?ids=${task.task_id}`)}>查看模型对比</GradientButton><Button onClick={() => navigate(`/features?dataset=${task.dataset_id}&task=${task.task_id}`)}>分析特征</Button><Button onClick={() => navigate(`/predict?dataset=${task.dataset_id}`)}>单样本预测</Button></div></GlassCard>}
      <GlassCard title={<><Icon name="history" /> 任务日志</>}><TrainingLogs taskId={task.task_id} active={!terminal(task.status)} revision={task.revision} /></GlassCard></>}
  </div>;
}

export function MonitoringCenterPage() {
  const navigate = useNavigate(), { settings } = usePreferences();
  const tasks = useLiveResource<{ items: Task[] }>('/api/v1/experiments', { interval: settings.pollSeconds * 1000 });
  const active = tasks.data?.items.filter(t => !terminal(t.status)) ?? [];
  return <div className="workspace-page"><PageTitle icon="monitor" title="实时任务中心" description="查看运行中的实验，或打开历史任务恢复完整监控状态。" extra={<GradientButton onClick={() => navigate('/lab')}>创建实验</GradientButton>} /><ErrorState message={tasks.error} /><GlassCard title={`正在运行 · ${active.length}`}>{active.length ? <TaskTable tasks={active} compact /> : <EmptyState title="当前没有运行中的实验" description="创建实验后将在这里显示真实任务进度" action={<Button onClick={() => navigate('/lab')}>进入模型实验室</Button>} />}</GlassCard><GlassCard title="最近任务"><TaskTable tasks={tasks.data?.items.slice(0, 10) ?? []} loading={tasks.loading} /></GlassCard></div>;
}

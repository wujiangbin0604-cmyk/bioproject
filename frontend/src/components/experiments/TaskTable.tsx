import { Button, Progress, Space, Table, Tooltip } from '@arco-design/web-react';
import { useNavigate } from 'react-router-dom';
import type { Task } from '../../api/platform';
import { downloadResult, names, number, terminal } from '../../api/platform';
import { dateTime, datasetNames, reportError } from '../../utils/platform';
import { ExperimentStatus } from '../ui/ExperimentStatus';
import { Icon } from '../ui/Icon';
export function TaskTable({ tasks, selected, onSelection, compact = false, loading = false }: { tasks: Task[]; selected?: string[]; onSelection?: (ids: string[]) => void; compact?: boolean; loading?: boolean }) {
  const navigate = useNavigate();
  return <Table<Task> className="experiment-table" size="small" rowKey="task_id" data={tasks} loading={loading} scroll={{ x: compact ? 700 : 1000 }} pagination={compact ? false : { pageSize: 10, showTotal: true, sizeCanChange: true }}
    rowSelection={onSelection ? { selectedRowKeys: selected, onChange: keys => onSelection(keys.map(String)), checkboxProps: row => ({ disabled: row.status !== 'completed' }) } : undefined}
    columns={[
      { title: '实验 / 数据集', width: 190, render: (_, t) => <button className="table-link" onClick={() => navigate(`/monitor/${t.task_id}`)}><strong>{datasetNames[t.dataset_id] ?? t.dataset_id}</strong><small>{t.task_id.slice(0, 10)}</small></button> },
      { title: '分类模型', width: 170, render: (_, t) => <span className="table-models">{t.experiment_config.algorithms?.map(a => names[a]).join(' / ')}</span> },
      ...(!compact ? [{ title: '特征方案', width: 150, render: (_: unknown, t: Task) => <span>{names[t.experiment_config.selection]}<small className="table-subtext">K = {t.experiment_config.selection === 'none' ? '全部' : t.experiment_config.k}</small></span> }] : []),
      { title: '状态', width: 120, render: (_, t) => <div><ExperimentStatus status={t.status} compact />{!terminal(t.status) && <Progress size="small" percent={t.progress} showText={false} style={{ width: 75, marginTop: 5 }} />}</div> },
      { title: '创建时间', width: 125, dataIndex: 'created_at', sorter: (a, b) => a.created_at.localeCompare(b.created_at), render: value => dateTime(value) },
      ...(!compact ? [{ title: '耗时', width: 90, render: (_: unknown, t: Task) => `${number(t.elapsed_seconds, 1)}s`, sorter: (a: Task, b: Task) => a.elapsed_seconds - b.elapsed_seconds }] : []),
      { title: '操作', width: compact ? 65 : 125, render: (_, t) => <Space size={3}><Tooltip content="查看实验详情"><Button size="mini" type="text" aria-label={`查看实验 ${t.task_id}`} icon={<Icon name="monitor" size={16} />} onClick={() => navigate(`/monitor/${t.task_id}`)} /></Tooltip>{!compact && <><Tooltip content="导出CSV"><Button size="mini" type="text" aria-label={`导出CSV ${t.task_id}`} icon={<Icon name="download" size={15} />} onClick={() => void downloadResult(t.task_id, 'csv').catch(reportError)} /></Tooltip><Button size="mini" type="text" onClick={() => void downloadResult(t.task_id, 'json').catch(reportError)}>JSON</Button></>}</Space> },
    ]} />;
}

import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Alert, Button, Card, Table, Tag } from '@arco-design/web-react';
import type { EChartsOption } from 'echarts';
import { api, getErrorMessage } from '../api/client';
import { EChart } from '../components/EChart';
import { PageHeading } from '../components/PageHeading';
import type { InferenceResult, LabCapabilities, LabConfiguration, LabTask, RegisteredModel } from '../types/lab';

const PREFIX = '/api/v1/lab';
const LAST_TASK = 'genescope-lab-task-v1';
const FINISHED = new Set(['completed', 'failed', 'cancelled', 'interrupted']);
const STATUS: Record<string, string> = { queued: '等待工作进程', loading: '核对开发数据', running: '交叉验证中', completed: '已完成', failed: '失败', cancelled: '已取消', interrupted: '运行中断' };
const url = (path: string) => `${api.defaults.baseURL ?? ''}${PREFIX}${path}`;
const number = (value: number | null | undefined, digits = 5) => value == null ? '—' : value.toFixed(digits);

export function LabPage() {
  const [mode, setMode] = useState<'inference' | 'training'>('inference');
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [capability, setCapability] = useState<LabCapabilities | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [results, setResults] = useState<InferenceResult[]>([]);
  const [history, setHistory] = useState<LabTask[]>([]);
  const [task, setTask] = useState<LabTask | null>(null);
  const [configuration, setConfiguration] = useState<LabConfiguration>({ classifier: 'linear_svm', selection: 'anova', k: 50, c: 1, cv_mode: 'standard' });
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [historyError, setHistoryError] = useState('');
  const [streamStatus, setStreamStatus] = useState('尚无任务');
  const active = !!task && !FINISHED.has(task.status);

  async function refreshHistory() {
    const response = await api.get<{ tasks: LabTask[] }>(`${PREFIX}/tasks`);
    setHistory(response.data.tasks);
  }

  async function refreshRegistry() {
    const response = await api.get<{ models: RegisteredModel[] }>(`${PREFIX}/models`);
    setModels(response.data.models);
    const available = response.data.models.filter(item => item.available).map(item => item.model_id);
    setSelected(previous => previous.length ? previous.filter(id => available.includes(id)) : available.includes('M1') ? ['M1'] : available.slice(0, 1));
  }

  useEffect(() => {
    let disposed = false;
    async function initialize() {
      try {
        // 模型推理不依赖训练记录。部署关闭训练时，不能让/tasks的拒绝阻断模式A。
        const [registry, capabilities] = await Promise.allSettled([
          api.get<{ models: RegisteredModel[] }>(`${PREFIX}/models`),
          api.get<LabCapabilities>(`${PREFIX}/capabilities`),
        ]);
        if (disposed) return;
        if (registry.status === 'fulfilled') {
          setModels(registry.value.data.models);
          const available = registry.value.data.models.filter(item => item.available).map(item => item.model_id);
          setSelected(available.includes('M1') ? ['M1'] : available.slice(0, 1));
        } else setError(getErrorMessage(registry.reason));
        if (capabilities.status === 'rejected') {
          setHistoryError(`训练状态读取失败：${getErrorMessage(capabilities.reason)}`);
          return;
        }
        setCapability(capabilities.value.data);
        if (!capabilities.value.data.available) return;
        const saved = localStorage.getItem(LAST_TASK);
        const [records, recovered] = await Promise.allSettled([
          api.get<{ tasks: LabTask[] }>(`${PREFIX}/tasks`),
          saved && /^[0-9a-f]{32}$/.test(saved) ? api.get<LabTask>(`${PREFIX}/tasks/${saved}`) : Promise.resolve(null),
        ]);
        if (disposed) return;
        if (records.status === 'fulfilled') setHistory(records.value.data.tasks);
        else setHistoryError(`运行记录暂不可读取：${getErrorMessage(records.reason)}`);
        if (recovered.status === 'fulfilled' && recovered.value) setTask(recovered.value.data);
        else if (recovered.status === 'rejected') {
          // 旧部署的任务可能不存在；保留模型推理和创建新任务的可用性。
          localStorage.removeItem(LAST_TASK);
          setHistoryError(`上次任务未恢复：${getErrorMessage(recovered.reason)}`);
        }
      } catch (reason) { if (!disposed) setError(getErrorMessage(reason)); }
      finally { if (!disposed) setLoading(false); }
    }
    void initialize();
    return () => { disposed = true; };
  }, []);

  const taskId = task?.task_id;
  const terminal = task ? FINISHED.has(task.status) : true;
  useEffect(() => {
    if (!taskId || terminal) { setStreamStatus(taskId ? '运行记录已保存' : '尚无任务'); return; }
    const source = new EventSource(url(`/tasks/${taskId}/events`));
    setStreamStatus('正在连接实时状态');
    source.onopen = () => setStreamStatus('SSE 实时连接');
    source.addEventListener('snapshot', (event) => {
      const snapshot: LabTask = JSON.parse((event as MessageEvent).data);
      setTask(snapshot);
      if (FINISHED.has(snapshot.status)) { source.close(); void refreshHistory().catch(() => undefined); }
    });
    source.onerror = () => setStreamStatus('连接中断，正在自动重连；任务继续执行');
    return () => source.close();
  }, [taskId, terminal]);

  async function infer() {
    if (!file) return;
    setBusy(true); setError(''); setResults([]);
    try {
      const body = new FormData(); body.append('file', file); body.append('model_ids', JSON.stringify(selected));
      const response = await api.post<{ results: InferenceResult[] }>(`${PREFIX}/predict`, body, { timeout: 90_000 });
      setResults(response.data.results);
    } catch (reason) { setError(getErrorMessage(reason)); }
    finally { setBusy(false); }
  }

  async function start() {
    setBusy(true); setError('');
    try {
      const response = await api.post<LabTask>(`${PREFIX}/tasks`, configuration);
      setTask(response.data); localStorage.setItem(LAST_TASK, response.data.task_id);
      void refreshHistory().catch(reason => setHistoryError(getErrorMessage(reason)));
    } catch (reason) { setError(getErrorMessage(reason)); }
    finally { setBusy(false); }
  }

  async function cancel() {
    if (!task) return;
    setBusy(true); setError('');
    try { const response = await api.post<LabTask>(`${PREFIX}/tasks/${task.task_id}/cancel`); setTask(response.data); void refreshHistory().catch(reason => setHistoryError(getErrorMessage(reason))); }
    catch (reason) { setError(getErrorMessage(reason)); }
    finally { setBusy(false); }
  }

  async function openTask(id: string) {
    try { const response = await api.get<LabTask>(`${PREFIX}/tasks/${id}`); setTask(response.data); localStorage.setItem(LAST_TASK, id); }
    catch (reason) { setError(getErrorMessage(reason)); }
  }

  const chart = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: 'axis' }, legend: { data: ['Macro-F1', 'Balanced Accuracy'], top: 0 },
    grid: { top: 42, right: 25, bottom: 42, left: 56 },
    xAxis: { type: 'category', name: '已完成验证折', nameLocation: 'middle', nameGap: 27, data: (task?.folds ?? []).map(f => `R${f.repeat_id}/F${f.fold_id}`) },
    yAxis: { type: 'value', min: 0, max: 1, name: '开发集验证分数' },
    series: [
      { name: 'Macro-F1', type: 'line', data: (task?.folds ?? []).map(f => f.validation_macro_f1), symbolSize: 6, color: '#225f86' },
      { name: 'Balanced Accuracy', type: 'line', data: (task?.folds ?? []).map(f => f.validation_balanced_accuracy), symbolSize: 6, color: '#168c82' },
    ],
  }), [task?.folds]);

  return <div className="page-stack lab-page">
    <PageHeading eyebrow="INTERACTIVE MODEL LAB" title="交互式模型实验室" description="在已验证的冻结模型上运行单样本推理，或在固定640例开发集上发起可追踪的模型实验。" extra={<Tag color="arcoblue">现场计算 · 独立记录</Tag>} />
    <div className="lab-mode-switch" role="group" aria-label="实验室模式">
      <button aria-pressed={mode === 'inference'} onClick={() => { setMode('inference'); setError(''); }}><b>A</b><span>多模型实时推理<small>冻结工件 · 单样本</small></span></button>
      <button aria-pressed={mode === 'training'} onClick={() => { setMode('training'); setError(''); }}><b>B</b><span>实时交叉验证<small>开发集 · 后台独立进程</small></span></button>
    </div>
    <div className="notice-callout">这里展示的是<b>现场推理输出</b>或<b>现场新实验指标</b>。此前冻结的研究成绩请查看<Link to="/models">历史模型性能</Link>。</div>
    {error && <Alert type="error" title="操作未完成" content={error} closable onClose={() => setError('')} />}
    {mode === 'inference' ? <>
      <div className="section-row"><h2>选择已验证的模型</h2><Button size="small" disabled={busy} onClick={() => void refreshRegistry().catch(reason => setError(getErrorMessage(reason)))}>刷新模型状态</Button></div>
      {loading ? <p>正在验证模型注册与运行环境…</p> : <div className="lab-model-grid">{models.map(model => <label key={model.model_id} className={`lab-model-card ${!model.available ? 'unavailable' : selected.includes(model.model_id) ? 'selected' : ''}`}>
        <div className="lab-model-top"><input type="checkbox" aria-label={`选择${model.model_id}`} disabled={!model.available || busy} checked={selected.includes(model.model_id)} onChange={event => setSelected(previous => event.target.checked ? [...previous, model.model_id] : previous.filter(id => id !== model.model_id))} /><strong>{model.model_id}</strong><Tag color={model.available ? 'green' : 'gray'}>{model.available ? '部署验证通过' : '不可用'}</Tag></div>
        <b>{model.name}</b><span>{model.available ? `${model.unique_gene_count?.toLocaleString()} 个实际独立基因` : model.reason}</span><small>{model.model_version ?? '未完成注册或运行环境不匹配'}</small>
      </label>)}</div>}
      <Card className="panel-card" bordered={false} title="上传一个RNA-Seq表达样本">
        <div className="lab-upload-row"><label className="lab-file-label">选择 UTF-8 CSV<input aria-label="实验室单样本CSV" type="file" accept=".csv" disabled={busy} onChange={event => { setResults([]); setError(''); const candidate = event.target.files?.[0]; if (candidate && (!candidate.name.toLowerCase().endsWith('.csv') || candidate.size > 5*1024*1024)) { setFile(null); setError('只接受最高5 MiB的CSV。'); } else setFile(candidate ?? null); }} /></label><span>{file?.name ?? '尚未选择文件'}</span><Button type="primary" loading={busy} disabled={busy || !file || !selected.length} onClick={infer}>运行所选模型</Button></div>
        <p className="lab-help">恰好1行，完整20,531个唯一 gene_* 列，可含 sample_id；按名称恢复列顺序。输入采用与模型训练一致的表达处理尺度。</p>
        {results.length > 0 && <><div className="lab-result-label"><Tag color="green">现场冻结模型推理输出</Tag><span>耗时包含模型缓存读取、加载及 predict。</span></div><Table rowKey="model_id" pagination={false} data={results} scroll={{ x: 760 }} columns={[
          { title: '模型', dataIndex: 'model_id' }, { title: '运行状态', dataIndex: 'status', render: value => value === 'success' ? '成功' : '不可用' },
          { title: '真实模型预测类别', dataIndex: 'predicted_class', render: value => value ?? '—' },
          { title: '推理耗时 ms', dataIndex: 'inference_ms', render: value => number(value, 2) },
          { title: '独立基因数', dataIndex: 'unique_gene_count' }, { title: '模型版本', dataIndex: 'model_version' }, { title: '诊断', dataIndex: 'error' },
        ]} /></>}
      </Card>
    </> : <>
      {historyError && <Alert type="warning" title="运行记录提示" content={historyError} closable onClose={() => setHistoryError('')} />}
      {!capability?.available && <Alert type="warning" title="现场训练当前不可用" content={capability?.reason ?? '正在检查原始开发数据与运行环境'} />}
      <Card className="panel-card" bordered={false} title="预设实验配置">
        <div className="lab-controls">
          <label>分类器<select aria-label="实验分类器" disabled={active || busy} value={configuration.classifier} onChange={event => setConfiguration({ ...configuration, classifier: event.target.value as LabConfiguration['classifier'] })}><option value="linear_svm">Linear SVM</option><option value="logistic_regression">Logistic Regression</option></select></label>
          <label>折内特征选择<select aria-label="实验特征选择" disabled={active || busy} value={configuration.selection} onChange={event => setConfiguration({ ...configuration, selection: event.target.value as LabConfiguration['selection'] })}><option value="anova">ANOVA F-score</option><option value="variance">原始表达高方差</option><option value="all">全部20,531个基因</option></select></label>
          <label>基因数量 K<select aria-label="实验特征数量" disabled={active || busy || configuration.selection === 'all'} value={configuration.k} onChange={event => setConfiguration({ ...configuration, k: Number(event.target.value) })}>{(capability?.k_values ?? [20,50,100,300,500,1000]).map(k => <option key={k} value={k}>{k}</option>)}</select></label>
          <label>参数 C<select aria-label="实验参数C" disabled={active || busy} value={configuration.c} onChange={event => setConfiguration({ ...configuration, c: Number(event.target.value) })}>{[.1,1,10].map(c => <option key={c} value={c}>{c}</option>)}</select></label>
          <label>交叉验证<select aria-label="实验交叉验证" disabled={active || busy} value={configuration.cv_mode} onChange={event => setConfiguration({ ...configuration, cv_mode: event.target.value as LabConfiguration['cv_mode'] })}><option value="standard">分层5折</option><option value="repeated">重复5折 × 20轮</option></select></label>
        </div>
        <div className="prediction-actions"><Button type="primary" onClick={start} loading={busy && !active} disabled={loading || !capability?.available || active || busy}>提交真实交叉验证任务</Button><span>固定随机种子42；完整Pipeline在每个训练折重新拟合。</span></div>
        <p className="lab-help">资源上限：同时1个训练任务、数值线程1、{capability?.limits.memory_limit_mb ?? '—'} MiB 内存、{capability?.limits.timeout_seconds ?? '—'}秒。</p>
      </Card>
      {task && <Card className="panel-card" bordered={false} title={<div className="lab-task-heading"><span>现场开发集交叉验证 <Tag color={task.status === 'completed' ? 'green' : task.status === 'failed' ? 'red' : 'orange'}>{STATUS[task.status] ?? task.status}</Tag></span><span className="lab-stream">{streamStatus}</span></div>}>
        <div className="lab-task-meta"><code>{task.task_id}</code><span>{task.configuration.selection} / {task.configuration.selection === 'all' ? 20531 : task.configuration.k} / {task.configuration.classifier} / C={task.configuration.c}</span></div>
        <div className="lab-progress"><progress aria-label="已完成交叉验证折数" max={task.total_folds} value={task.completed_folds} /><strong>{task.completed_folds} / {task.total_folds} 折</strong><span>{number(task.elapsed_seconds, 1)} s</span></div>
        <p aria-live="polite">{task.message}</p>
        {task.error && <Alert type="error" title="工作进程诊断" content={task.error} />}
        <div className="prediction-actions">{active && <Button status="danger" disabled={busy} onClick={cancel}>取消当前任务</Button>}<a className="lab-export" href={url(`/tasks/${task.task_id}/export`)}>导出当前运行记录 ZIP</a></div>
        {(task.folds?.length ?? 0) > 0 ? <><EChart option={chart} style={{ height: 320 }} />
          <Table rowKey="evaluation_index" data={task.folds} pagination={{ pageSize: 5 }} scroll={{ x: 750 }} columns={[
            { title: '验证折', render: (_, row) => `R${row.repeat_id} / F${row.fold_id}` },
            { title: '验证 Macro-F1', dataIndex: 'validation_macro_f1', render: value => number(value) },
            { title: '验证 Balanced Acc.', dataIndex: 'validation_balanced_accuracy', render: value => number(value) },
            { title: '训练 Macro-F1', dataIndex: 'train_macro_f1', render: value => number(value) },
            { title: '训练−验证', dataIndex: 'macro_f1_gap', render: value => number(value) },
            { title: '拟合耗时 s', dataIndex: 'fit_seconds', render: value => number(value, 2) },
          ]} /></> : <div className="remote-state">完成首个验证折后绘制真实指标曲线。</div>}
        {task.summary && <div className="notice-callout">验证折 Macro-F1均值 {number(task.summary.fold.validation_macro_f1.mean, 6)}；样本标准差 {number(task.summary.fold.validation_macro_f1.sample_std, 6)}。</div>}
      </Card>}
      <Card className="panel-card" bordered={false} title="现场实验运行记录" extra={<Button size="small" onClick={() => void refreshHistory().catch(reason => setError(getErrorMessage(reason)))}>刷新记录</Button>}>
        {history.length ? <div className="lab-history">{history.slice(0, 20).map(item => <button key={item.task_id} onClick={() => void openTask(item.task_id)}><code>{item.task_id.slice(0, 10)}</code><span>{item.configuration.selection} · {item.configuration.classifier} · {new Date(item.created_at).toLocaleString('zh-CN')}</span><Tag>{STATUS[item.status] ?? item.status} {item.completed_folds}/{item.total_folds}</Tag></button>)}</div> : <p>尚无现场训练记录。</p>}
      </Card>
    </>}
  </div>;
}

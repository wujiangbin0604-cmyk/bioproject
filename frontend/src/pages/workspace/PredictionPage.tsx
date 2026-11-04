import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Descriptions, Select, Space, Steps, Tag } from '@arco-design/web-react';
import { useSearchParams } from 'react-router-dom';
import type { Model } from '../../api/platform';
import { names } from '../../api/platform';
import { api, downloadExample, getErrorMessage } from '../../api/client';
import { useLiveResource } from '../../hooks/useLiveResource';
import { checkPredictionCsv } from '../../utils/predictionCsv';
import { saveBlob } from '../../utils/platform';
import { GlassCard } from '../../components/ui/GlassCard';
import { PageTitle } from '../../components/ui/PageTitle';
import { GradientButton } from '../../components/ui/GradientButton';
import { DatasetPicker } from '../../components/ui/DatasetPicker';
import { EmptyState, ErrorState, LoadingSkeleton } from '../../components/ui/States';
import { Icon } from '../../components/ui/Icon';
import { FileUploadArea } from '../../components/prediction/FileUploadArea';
import { PredictionResultCard } from '../../components/prediction/PredictionResultCard';
import type { PredictionResult } from '../../components/prediction/PredictionResultCard';

const frozenFeatures = Array.from({ length: 20531 }, (_, i) => `gene_${i}`);
export default function PredictionPage() {
  const [params] = useSearchParams(), [dataset, setDataset] = useState(params.get('dataset') ?? 'pancan'), [model, setModel] = useState(params.get('model') ?? (dataset === 'pancan' ? 'frozen_m1' : ''));
  const [file, setFile] = useState<File>(), [text, setText] = useState(''), [error, setError] = useState(''), [step, setStep] = useState(0), [busy, setBusy] = useState(false), [checking, setChecking] = useState(false), [progress, setProgress] = useState<number | null>(null), [result, setResult] = useState<PredictionResult>(), [synthetic, setSynthetic] = useState(false);
  const readId = useRef(0), request = useRef<AbortController>();
  useEffect(() => () => { readId.current++; request.current?.abort(); }, []);
  const models = useLiveResource<{ items: Model[] }>(`/api/v1/models?dataset_id=${dataset}`);
  const detail = useLiveResource<Model>(model && model !== 'frozen_m1' ? `/api/v1/models/${model}` : null);
  const expected = model === 'frozen_m1' ? frozenFeatures : detail.data?.feature_names;
  const check = useMemo(() => text ? checkPredictionCsv(text, step > 0 ? expected : undefined) : undefined, [text, expected, step]);
  const options = [...(dataset === 'pancan' ? [{ value: 'frozen_m1', label: '原冻结 M1 · ANOVA50 + LinearSVC' }] : []), ...(models.data?.items ?? []).map(m => ({ value: m.model_id, label: `${names[m.algorithm]} · ${m.model_version}` }))];
  async function choose(candidate?: File, isExample = false) {
    const id = ++readId.current; setFile(undefined); setText(''); setError(''); setResult(undefined); setProgress(null); setStep(0); setSynthetic(isExample);
    if (!candidate) { setChecking(false); return; }
    if (!candidate.name.toLowerCase().endsWith('.csv') || candidate.size > 5 * 1024 ** 2 || !candidate.size) { setError('请选择非空CSV文件，大小不超过5 MiB'); return; }
    setChecking(true);
    try { const content = await candidate.text(); if (id !== readId.current) return; const valid = checkPredictionCsv(content); if (valid.error) setError(valid.error); else { setFile(candidate); setText(content); } }
    catch { if (id === readId.current) setError('文件读取失败，请重新选择'); }
    finally { if (id === readId.current) setChecking(false); }
  }
  async function predict() {
    if (!file || !model || busy || check?.error || !expected) return;
    const controller = new AbortController(); request.current = controller; setBusy(true); setError(''); setResult(undefined); setProgress(0);
    const body = new FormData(); body.append('file', file); body.append('dataset_id', dataset); body.append('model_id', model);
    try { const response = await api.post<{ data: PredictionResult }>('/api/v1/predict', body, { timeout: 60000, signal: controller.signal, onUploadProgress: event => { if (event.total) setProgress(Math.round(event.loaded / event.total * 100)); } }); setResult(response.data.data); setStep(2); }
    catch (e) { if (!controller.signal.aborted) setError(getErrorMessage(e)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <div className="workspace-page"><PageTitle icon="target" title="单样本预测" description="上传表达样本，选择同数据集模型，查看真实类别预测。" /><GlassCard className="prediction-stepper"><Steps current={step + 1} size="small">{['上传样本', '选择模型', '预测结果'].map((title, i) => <Steps.Step key={title} title={title} status={i < step ? 'finish' : i === step ? 'process' : 'wait'} />)}</Steps></GlassCard><div className="prediction-workspace"><GlassCard title={<><Icon name={step === 0 ? 'upload' : 'flask'} />{step === 0 ? '上传样本数据' : '预测配置'}</>}>
    <div className="field-label">所属数据集</div><DatasetPicker value={dataset} onChange={v => { setDataset(v); setModel(v === 'pancan' ? 'frozen_m1' : ''); void choose(); }} disabled={busy} readyOnly />
    <div className="prediction-file-section"><FileUploadArea file={file} busy={busy || checking} progress={progress} onChange={candidate => void choose(candidate)} /></div>{checking && <LoadingSkeleton rows={2} />}{check && !check.error && <div className="csv-validation"><Icon name="check" size={16} />格式通过 · 1个样本 · {check.featureCount.toLocaleString()} 个表达特征</div>}
    {step > 0 && <div className="content-enter prediction-model-section"><div className="field-label">可用模型</div><Select aria-label="预测模型" value={model || undefined} options={options} placeholder={models.loading ? '正在加载模型' : '选择注册模型'} disabled={busy} onChange={v => { setModel(v); setResult(undefined); setStep(1); setError(''); setProgress(null); }} />{detail.loading && <LoadingSkeleton rows={2} />}<ErrorState message={check?.error} />{!options.length && <EmptyState title="尚无已注册模型" description="先在模型实验室完成此数据集的训练" />}</div>}
    <ErrorState message={error || models.error || detail.error} /><div className="prediction-navigation"><Space>{step > 0 && <Button disabled={busy} onClick={() => { setStep(0); setResult(undefined); }}>上一步</Button>}{dataset === 'pancan' && <Button type="text" disabled={busy || checking} onClick={async () => { try { const blob = await downloadExample(); saveBlob(blob, 'synthetic_format_example.csv'); await choose(new File([blob], 'synthetic_format_example.csv', { type: 'text/csv' }), true); } catch (e) { setError(getErrorMessage(e)); } }}>加载合成格式示例</Button>}</Space>{step === 0 ? <GradientButton disabled={!file || checking || !!check?.error} onClick={() => setStep(1)}>下一步 <Icon name="arrow" size={16} /></GradientButton> : <GradientButton loading={busy} disabled={!file || !model || !expected || !!check?.error || detail.loading || busy} onClick={() => void predict()}>{busy ? progress === 100 ? '模型推理中' : '正在上传' : '开始预测'} <Icon name="target" size={16} /></GradientButton>}</div>
    </GlassCard><aside className="prediction-detail">{result ? <PredictionResultCard result={result} synthetic={synthetic} /> : <GlassCard title={<><Icon name="info" /> 模型与输入要求</>}>{model === 'frozen_m1' ? <><Tag color="arcoblue">原冻结研究 · PANCAN</Tag><h3>ANOVA Top50 + LinearSVC</h3><p className="small-note">完整输入为20,531个 gene_* 列，与原研究表达尺度一致；原可信Pipeline选出50个特征用于推理。</p></> : detail.data ? <Descriptions column={1} data={[{ label: '版本', value: detail.data.model_version }, { label: '评价范围', value: detail.data.validation_scope }, { label: '输入尺度', value: detail.data.input_preprocessing }, { label: '完整输入', value: `${expected?.length.toLocaleString()} 个特征` }, { label: '入选特征', value: detail.data.n_features }]} /> : <EmptyState title="选择模型后查看输入要求" />}<div className="input-requirements"><p><Icon name="check" size={15} />表头名称与完整模型特征清单一致</p><p><Icon name="check" size={15} />仅1行样本，数值有限且无缺失</p><p><Icon name="check" size={15} />可带 sample_id 列，表达列允许重排</p><p><Icon name="check" size={15} />与模型使用相同的数据处理和表达尺度</p></div><Button disabled={!expected} icon={<Icon name="download" size={15} />} onClick={() => saveBlob(new Blob([expected!.join('\n')], { type: 'text/plain' }), `${model}_input_features.txt`)}>下载完整输入特征清单</Button><p className="small-note">上传数据仅用于本次推理。模型未提供校准概率或风险评分，结果用于科研与教学。</p></GlassCard>}</aside></div></div>;
}

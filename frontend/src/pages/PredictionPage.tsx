import { useRef, useState } from 'react';
import { Alert, Button, Card, Grid, Tag } from '@arco-design/web-react';
import { getErrorMessage, uploadPrediction, downloadExample } from '../api/client';
import { useApi } from '../hooks';
import type { HealthData, PredictionData } from '../types/api';
import { PageHeading } from '../components/PageHeading';
import { CLASS_LABELS } from '../constants';

export function PredictionPage() {
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<PredictionData | null>(null);
  const [example, setExample] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const health = useApi<HealthData>('/api/v1/health');
  const modelAvailable = health.envelope?.data.model_available === true;

  function chooseFile(candidate?: File) {
    setFile(null); setResult(null); setError(''); setExample(false);
    if (!candidate) return;
    if (!candidate.name.toLowerCase().endsWith('.csv')) { setError('只接受CSV文件。'); return; }
    if (candidate.size > 5 * 1024 * 1024) { setError('文件超过5 MiB限制。'); return; }
    setFile(candidate);
  }

  async function submit() {
    if (!file) return;
    setBusy(true); setError(''); setResult(null);
    try { setResult(await uploadPrediction(file)); }
    catch (reason) { setError(getErrorMessage(reason)); }
    finally { setBusy(false); }
  }

  async function loadExample() {
    setError(''); setResult(null); setExample(true);
    try { const blob = await downloadExample(); setFile(new File([blob], 'sample_input.csv', { type: 'text/csv' })); }
    catch (reason) { setError(getErrorMessage(reason)); }
  }

  return <div className="page-stack">
    <PageHeading eyebrow="FROZEN M1 INFERENCE" title="单样本预测" description="上传恰好一行、包含20,531个唯一命名基因列的CSV。输入由项目原有校验器检查，并调用已冻结M1 Pipeline。" extra={<Tag color={modelAvailable ? 'green' : 'orange'}>{modelAvailable ? '模型可用' : '模型环境不可用'}</Tag>} />
    {!modelAvailable && !health.loading && <Alert type="warning" title="当前推理环境与冻结模型要求不匹配" content={health.envelope?.data.model_unavailable_reason ?? '请查看部署依赖说明。结果浏览功能仍可使用。'} />}
    <Grid.Row gutter={[16, 16]}>
      <Grid.Col xs={24} xl={15}>
        <Card className="panel-card prediction-card" bordered={false} title={<div><div className="panel-title">输入一个表达样本</div><div className="panel-subtitle">UTF-8 CSV · 最高5 MiB · 可选 sample_id 列</div></div>}>
          <div className={`upload-zone ${dragging ? 'is-dragging' : ''}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); chooseFile(event.dataTransfer.files[0]); }}>
            <input ref={inputRef} type="file" accept=".csv,text/csv" className="file-input" onChange={(event) => chooseFile(event.target.files?.[0])} />
            <div className="upload-symbol">CSV</div><strong>拖拽CSV文件到这里</strong><span>或从本机选择一个文件</span>
            <Button onClick={() => inputRef.current?.click()}>选择 CSV 文件</Button>
          </div>
          {file && <div className="selected-file"><span className="file-chip">CSV</span><div><strong>{file.name}</strong><small>{(file.size / 1024).toFixed(1)} KB{example ? ' · 合成格式示例' : ''}</small></div><Button type="text" onClick={() => { setFile(null); setExample(false); setResult(null); }}>移除</Button></div>}
          {error && <Alert className="prediction-error" type="error" title="无法完成预测" content={error} />}
          <div className="prediction-actions"><Button type="primary" disabled={!file || busy} loading={busy} onClick={submit}>{busy ? '正在校验并推理…' : '运行单样本预测'}</Button><Button onClick={loadExample}>加载格式示例</Button><span>合成格式示例</span></div>
          {result && <div className="prediction-result"><div className="result-topline"><span>模型输出</span><Tag color="green">推理完成</Tag></div><div className="result-class"><strong>{result.predicted_class}</strong><span>{CLASS_LABELS[result.predicted_class] ?? '未知类别'}</span></div><div className="result-facts">
            <div><span>模型</span><strong>{result.model_name}</strong></div><div><span>版本</span><strong>{result.model_version}</strong></div><div><span>输入特征</span><strong>{result.input_feature_count.toLocaleString()}</strong></div><div><span>模型选择</span><strong>{result.selected_feature_count} 个基因</strong></div><div><span>恢复列顺序</span><strong>{result.input_columns_reordered ? '是' : '否'}</strong></div>
          </div></div>}
        </Card>
      </Grid.Col>
      <Grid.Col xs={24} xl={9}>
        <Card className="panel-card" bordered={false} title={<div><div className="panel-title">输入格式要求</div><div className="panel-subtitle">由原有 Python 部署校验器最终裁决</div></div>}>
          <div className="requirements-list">{['恰好一行表达值', '20,531个唯一 gene_* 列', '列名与模型训练特征完全一致', '可调整列顺序，按基因名恢复', '不允许缺失、额外、重复、非数值或无穷值', 'sample_id 可选且不会进入模型'].map((item, index) => <div key={item}><span>{String(index + 1).padStart(2, '0')}</span>{item}</div>)}</div>
          <div className="requirements-note">上传后按特征列名校验并运行模型推理。</div>
        </Card>
        <Card className="panel-card class-key-card" bordered={false} title={<div><div className="panel-title">类别缩写</div><div className="panel-subtitle">模型只在五类肿瘤中输出一个类别</div></div>}>
          {Object.entries(CLASS_LABELS).map(([code, label]) => <div className="class-key-row" key={code}><strong>{code}</strong><span>{label}</span></div>)}
        </Card>
      </Grid.Col>
    </Grid.Row>
  </div>;
}

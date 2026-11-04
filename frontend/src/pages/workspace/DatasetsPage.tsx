import { useState } from 'react';
import { Button, Descriptions, Drawer, Input, Message, Select, Space, Table, Tag, Upload } from '@arco-design/web-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { Dataset, Task } from '../../api/platform';
import { api, getErrorMessage } from '../../api/client';
import { useLiveResource, useDebouncedValue } from '../../hooks/useLiveResource';
import { readStored, writeStored } from '../../hooks/usePreferences';
import { GlassCard } from '../../components/ui/GlassCard';
import { PageTitle } from '../../components/ui/PageTitle';
import { AnimatedStat } from '../../components/ui/AnimatedStat';
import { ErrorState, EmptyState, LoadingSkeleton } from '../../components/ui/States';
import { GradientButton } from '../../components/ui/GradientButton';
import { Icon } from '../../components/ui/Icon';
import { ExperimentStatus } from '../../components/ui/ExperimentStatus';
import { InteractiveDatasetCard } from '../../components/datasets/InteractiveDatasetCard';
import { HeatmapExplorer } from '../../components/charts/HeatmapExplorer';
import { EChart } from '../../components/EChart';
import { qualityNames } from '../../utils/platform';

export default function DatasetsPage() {
  const navigate = useNavigate(), [params] = useSearchParams();
  const [refresh, setRefresh] = useState(0), [active, setActive] = useState(params.get('dataset') ?? '');
  const [view, setView] = useState<'cards' | 'table'>('cards'), [search, setSearch] = useState(''), [status, setStatus] = useState('all');
  const [favorites, setFavorites] = useState<string[]>(() => readStored('genescope-favorite-datasets', []));
  const [importOpen, setImportOpen] = useState(false), [importKey, setImportKey] = useState('pancan'), [busy, setBusy] = useState(false);
  const query = useDebouncedValue(search);
  const list = useLiveResource<{ items: Dataset[] }>('/api/v1/datasets', { refresh });
  const summary = useLiveResource<Dataset>(active ? `/api/v1/datasets/${active}/summary` : null, { refresh });
  const selected = list.data?.items.find(d => d.dataset_id === active), items = list.data?.items ?? [];
  const shown = items.filter(d => `${d.name} ${d.platform} ${d.dataset_id}`.toLowerCase().includes(query.toLowerCase()) && (status === 'all' || status === 'favorite' ? status !== 'favorite' || favorites.includes(d.dataset_id) : d.status === status));
  const favorite = (key: string) => setFavorites(old => { const next = old.includes(key) ? old.filter(v => v !== key) : [...old, key]; writeStored('genescope-favorite-datasets', next); return next; });
  async function importData(download = false, file?: File) {
    if (file && file.size > 100 * 1024 ** 2) { Message.error('矩阵文件超过100 MiB限制'); return; }
    setBusy(true);
    try { const body = new FormData(); body.append('dataset_id', importKey); body.append('download', String(download)); if (file) body.append('file', file);
      const { data } = await api.post<Task>('/api/v1/datasets/import', body, { timeout: 120000 });
      Message.success(`已创建导入任务 ${data.task_id.slice(0, 8)}`); navigate(`/monitor/${data.task_id}`);
    } catch (e) { Message.error(getErrorMessage(e)); } finally { setBusy(false); }
  }
  return <div className="workspace-page"><PageTitle icon="database" title="数据集中心" description="管理表达数据、样本标签与划分协议，为每次实验保留完整来源。" extra={<Space><Button icon={<Icon name="refresh" size={16} />} onClick={() => setRefresh(v => v + 1)}>刷新状态</Button><GradientButton icon={<Icon name="upload" size={17} />} onClick={() => setImportOpen(true)}>导入数据集</GradientButton></Space>} />
    <div className="dataset-stats-row"><AnimatedStat label="已接入数据集" value={list.data?.items.length} detail="四类独立研究任务" icon="database" /><AnimatedStat label="实际纳入样本" value={list.data ? items.reduce((n, d) => n + (d.samples ?? 0), 0) : undefined} detail="各数据集独立分析，不混合训练" icon="features" tone="purple" index={1} /><AnimatedStat label="数据已就绪" value={list.data?.items.filter(d => d.status === 'ready').length} detail="标签与质量已校验" icon="check" tone="mint" index={2} /></div>
    <div className="workspace-toolbar"><Input.Search aria-label="搜索数据集" value={search} onChange={setSearch} placeholder="搜索数据集、平台或 accession" allowClear /><Select aria-label="筛选数据集状态" value={status} onChange={setStatus} options={[{ value: 'all', label: '全部数据集' }, { value: 'ready', label: '已就绪' }, { value: 'pending', label: '待导入' }, { value: 'favorite', label: '我的收藏' }]} style={{ width: 145 }} /><span className="toolbar-spacer" /><div className="view-switch"><Button type={view === 'cards' ? 'primary' : 'text'} aria-label="卡片视图" icon={<Icon name="grid" size={17} />} onClick={() => setView('cards')} /><Button type={view === 'table' ? 'primary' : 'text'} aria-label="表格视图" icon={<Icon name="list" size={18} />} onClick={() => setView('table')} /></div></div><ErrorState message={list.error} />
    {list.loading ? <LoadingSkeleton rows={6} /> : !shown.length ? <EmptyState title="没有匹配的数据集" description="调整关键词或状态筛选" /> : view === 'cards' ? <div className="dataset-card-grid">{shown.map((d, i) => <InteractiveDatasetCard key={d.dataset_id} dataset={d} index={i} favorite={favorites.includes(d.dataset_id)} onFavorite={() => favorite(d.dataset_id)} onOpen={() => setActive(d.dataset_id)} onImport={() => { setImportKey(d.dataset_id); setImportOpen(true); }} />)}</div> : <GlassCard><Table<Dataset> rowKey="dataset_id" data={shown} pagination={false} scroll={{ x: 800 }} columns={[{ title: '数据集', dataIndex: 'name', render: (_, d) => <button className="table-link" onClick={() => setActive(d.dataset_id)}>{d.name}</button> }, { title: '平台', dataIndex: 'platform' }, { title: '实际样本数', dataIndex: 'samples', sorter: (a, b) => (a.samples ?? 0) - (b.samples ?? 0) }, { title: '特征数', dataIndex: 'features' }, { title: '类别数', dataIndex: 'classes' }, { title: '状态', render: (_, d) => <ExperimentStatus status={d.status} /> }, { title: '操作', render: (_, d) => <Button size="mini" onClick={() => setActive(d.dataset_id)}>查看详情</Button> }]} /></GlassCard>}
    <Drawer className="dataset-detail-drawer" title={selected?.name ?? '数据集详情'} visible={!!active} onCancel={() => setActive('')} footer={null} width="min(850px, 95vw)">
      {selected && <div className="workspace-page"><div className="drawer-data-heading"><span className="dataset-symbol"><Icon name="database" size={28} /></span><div><ExperimentStatus status={selected.status} /><p>{selected.task_definition}</p></div></div><Descriptions column={1} data={[{ label: '官方来源', value: <a className="source-link" href={selected.source_url} target="_blank" rel="noreferrer">{selected.source_url}</a> }, { label: '表达处理', value: selected.preprocessing }, { label: '数据划分', value: selected.split_protocol }, { label: '特征命名', value: selected.feature_namespace }, { label: '版本', value: selected.version ?? '待导入' }]} /><ErrorState message={summary.error} />{summary.loading ? <LoadingSkeleton rows={5} /> : summary.data && <><GlassCard title="类别样本分布"><EChart style={{ height: 240 }} option={{ tooltip: { trigger: 'axis' }, grid: { left: 110, right: 25, top: 10, bottom: 30 }, xAxis: { type: 'value' }, yAxis: { type: 'category', data: Object.keys(summary.data.class_counts) }, series: [{ type: 'bar', data: Object.values(summary.data.class_counts), itemStyle: { color: '#54c7c9', borderRadius: [0, 5, 5, 0] }, barMaxWidth: 22 }] }} /></GlassCard><GlassCard title="数据质量报告"><Descriptions column={2} data={Object.entries(summary.data.quality ?? {}).map(([key, value]) => ({ label: qualityNames[key] ?? key, value: value == null ? '不适用' : typeof value === 'boolean' ? value ? '是' : '否' : typeof value === 'number' && !Number.isInteger(value) ? value.toFixed(3) : String(value) }))} /><p className="small-note">{summary.data.provenance?.official_processing?.join('\n')}</p><p className="small-note hash-note">SHA-256：{summary.data.provenance?.source_sha256}</p></GlassCard><GlassCard title="表达热图"><HeatmapExplorer data={summary.data.heatmap} /></GlassCard></>}</div>}
    </Drawer>
    <Drawer title="导入官方表达矩阵" visible={importOpen} onCancel={() => setImportOpen(false)} footer={null} width="min(520px, 95vw)"><div className="workspace-page"><p className="small-note">选择已登记的数据集。下载和导入将在独立任务中执行，进度可在监控页查看。</p><Select aria-label="导入目标数据集" value={importKey} onChange={setImportKey} options={items.map(d => ({ value: d.dataset_id, label: d.name }))} /><Space direction="vertical" style={{ width: '100%' }}><GradientButton long loading={busy} onClick={() => importData(false)}>导入本地已有数据</GradientButton>{importKey !== 'pancan' && <><Button long loading={busy} onClick={() => importData(true)}>从 GEO 官方源下载并导入</Button><Upload drag accept=".txt,.gz" showUploadList={false} disabled={busy} beforeUpload={file => { if (!/\.txt(\.gz)?$/i.test(file.name)) { Message.error('仅接受Series Matrix .txt或.txt.gz'); return false; } void importData(false, file); return false; }}><div className="upload-empty"><Icon name="upload" size={35} /><strong>拖拽 Series Matrix 到这里</strong><span>或点击选择文件 · 最大100 MiB</span></div></Upload></>}</Space><Tag color="arcoblue">标签和患者分组必须可从官方字段确认</Tag></div></Drawer>
  </div>;
}

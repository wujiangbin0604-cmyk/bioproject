import { Button, Space, Tag, Tooltip } from '@arco-design/web-react';
import type { Dataset } from '../../api/platform';
import { GlassCard } from '../ui/GlassCard';
import { ExperimentStatus } from '../ui/ExperimentStatus';
import { Icon } from '../ui/Icon';
export function InteractiveDatasetCard({ dataset, favorite, onFavorite, onOpen, onImport, index }: { dataset: Dataset; favorite: boolean; onFavorite: () => void; onOpen: () => void; onImport: () => void; index: number }) {
  const tone = ['blue', 'purple', 'cyan', 'mint'][index % 4];
  return <GlassCard hover className={`interactive-dataset-card tone-${tone}`} title={<button className="dataset-title-link" onClick={onOpen}><span className="dataset-symbol"><Icon name="database" size={24} /></span><span>{dataset.name}<small>{dataset.platform} · {dataset.data_type === 'microarray' ? '微阵列' : 'RNA-Seq'}</small></span></button>} extra={<Tooltip content={favorite ? '取消收藏' : '收藏数据集'}><Button className={favorite ? 'favorite-button is-favorite' : 'favorite-button'} type="text" shape="circle" aria-label={`${favorite ? '取消收藏' : '收藏'} ${dataset.name}`} aria-pressed={favorite} icon={<Icon name="star" size={18} />} onClick={onFavorite} /></Tooltip>}>
    <div className="dataset-card-topline"><ExperimentStatus status={dataset.status} /><Tag color={tone === 'purple' ? 'purple' : 'arcoblue'}>{dataset.classes ?? '—'} 类任务</Tag></div><p className="dataset-task-description">{dataset.task_definition}</p>
    <div className="dataset-count-grid"><div><span>实际纳入样本</span><strong>{dataset.samples?.toLocaleString() ?? '—'}</strong></div><div><span>表达特征</span><strong>{dataset.features?.toLocaleString() ?? '—'}</strong></div></div><div className="dataset-class-tags">{Object.entries(dataset.class_counts ?? {}).slice(0, 5).map(([name, count]) => <span key={name}>{name}<b>{count}</b></span>)}</div>
    <p className="dataset-protocol-text"><Icon name="check" size={13} />{dataset.dataset_id === 'pancan' ? '固定开发集 · 原保留集隔离' : dataset.dataset_id === 'gse44076' ? '患者分组交叉验证' : '独立分层交叉验证'}</p>
    <div className="dataset-card-footer"><a href={dataset.source_url} target="_blank" rel="noreferrer">官方来源 ↗</a><Space><Button size="small" onClick={onImport}>{dataset.status === 'ready' ? '刷新导入' : '导入数据'}</Button><Button size="small" type="primary" onClick={onOpen}>查看详情</Button></Space></div>
  </GlassCard>;
}

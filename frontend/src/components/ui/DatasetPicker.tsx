import { Select } from '@arco-design/web-react';
import type { Dataset } from '../../api/platform';
import { useLiveResource } from '../../hooks/useLiveResource';
export function DatasetPicker({ value, onChange, readyOnly = false, label = '选择数据集', clear = false, disabled = false }: { value: string; onChange: (v: string) => void; readyOnly?: boolean; label?: string; clear?: boolean; disabled?: boolean }) {
  const list = useLiveResource<{ items: Dataset[] }>('/api/v1/datasets');
  return <Select aria-label={label} disabled={disabled} value={value || undefined} placeholder="选择数据集" allowClear={clear} onChange={v => onChange(v ?? '')} options={(list.data?.items ?? []).map(d => ({ value: d.dataset_id, label: `${d.name}${d.status === 'ready' ? '' : '（待导入）'}`, disabled: readyOnly && d.status !== 'ready' }))} />;
}

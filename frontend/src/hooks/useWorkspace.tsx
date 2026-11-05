import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { PropsWithChildren } from 'react';
import type { Dataset, Model, Task } from '../api/platform';
import { readStored, usePreferences, writeStored } from './usePreferences';
import { useLiveResource } from './useLiveResource';

function useWorkspaceResources() {
  const { settings } = usePreferences();
  const interval = settings.pollSeconds * 1000;
  const datasets = useLiveResource<{ items: Dataset[] }>('/api/v1/datasets', { interval });
  const tasks = useLiveResource<{ items: Task[] }>('/api/v1/experiments', { interval });
  const models = useLiveResource<{ items: Model[] }>('/api/v1/models', { interval });
  const [selected, setSelected] = useState(() => readStored<string>('genescope-dashboard-dataset-v1', 'pancan'));
  const items = datasets.data?.items;
  const datasetId = items?.length && !items.some(item => item.dataset_id === selected) ? items[0].dataset_id : selected;
  useEffect(() => { writeStored('genescope-dashboard-dataset-v1', datasetId); }, [datasetId]);
  return useMemo(() => ({ datasets, tasks, models, datasetId, selectDataset: setSelected }), [datasets, tasks, models, datasetId]);
}

const WorkspaceContext = createContext<ReturnType<typeof useWorkspaceResources> | null>(null);
export function WorkspaceProvider({ children }: PropsWithChildren) {
  const value = useWorkspaceResources();
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error('WorkspaceProvider is required');
  return value;
}

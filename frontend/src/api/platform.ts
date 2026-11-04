import { useEffect, useState } from 'react';
import { api, getErrorMessage } from './client';

export interface Dataset {
  dataset_id: string; name: string; data_type: string; platform: string; source_url: string;
  status: string; samples: number | null; features: number | null; classes: number | null;
  version: string; class_counts: Record<string, number>; task_definition: string; split_protocol: string;
  preprocessing: string; feature_namespace: string; error?: string; quality?: Record<string, number | boolean | null>;
  provenance?: { official_processing?: string[]; source_sha256?: string; probe_mapping?: string };
  heatmap?: { samples: string[]; features: string[]; values: number[][]; scope: string };
}
export interface Config {
  dataset_id: string; algorithms: string[]; selection: string; k: number; folds: number; seed: number;
  repeats: number; c: number; gamma: string; n_estimators: number; max_depth: number | null;
}
export interface Fold {
  algorithm: string; repeat: number; fold: number; macro_f1: number; accuracy: number;
  balanced_accuracy: number; fit_seconds: number; n_features: number;
}
export interface Task {
  revision?: number;
  task_id: string; dataset_id: string; kind: string; status: string; experiment_config: Config;
  created_at: string; started_at: string | null; finished_at: string | null; current_stage: string;
  progress: number; completed_folds: number; total_folds: number; elapsed_seconds: number; folds: Fold[];
  error: string | null; errors: string[];
}
export interface Result {
  algorithm: string; metrics: Record<string, { mean: number; std: number }>; n_features: number;
  fit_seconds: number; jaccard_mean: number | null; labels: string[]; confusion_matrix: number[][];
  per_class: Record<string, { f1_score?: number; 'f1-score'?: number; precision?: number; recall?: number }>;
  model_id: string; ranking: { feature: string; score: number | null }[];
  selection_frequency: { feature: string; count: number; frequency: number }[];
}
export interface Results { task_id?: string; dataset_id: string; dataset_version: string; task_definition: string; split_protocol: string; split_sha256: string; configuration: Config; results: Result[] }
export interface Model { model_id: string; dataset_id: string; algorithm: string; model_version: string; n_features: number; feature_names?: string[]; validation_scope: string; input_preprocessing: string; runtime_versions: Record<string, string> }

export const names: Record<string, string> = { linear_svc: 'LinearSVC', logistic_regression: 'Logistic Regression', random_forest: 'Random Forest', rbf_svm: 'RBF SVM', none: '全特征', anova: 'ANOVA F-score', variance: 'Variance Top-K', coefficient: '线性模型系数' };
export const statusNames: Record<string, string> = { queued: '排队中', preparing: '准备中', running: '运行中', completed: '已完成', failed: '失败', cancel_requested: '正在取消', cancelled: '已取消', ready: '已就绪', pending: '待导入' };
export const terminal = (status: string) => ['completed', 'failed', 'cancelled'].includes(status);
export const number = (v: number | null | undefined, digits = 4) => v == null ? '—' : v.toFixed(digits);

export function useResource<T>(path: string | null, refresh = 0) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    setData(undefined); setError('');
    if (!path) return;
    const controller = new AbortController();
    setLoading(true);
    api.get<T>(path, { signal: controller.signal }).then(r => setData(r.data)).catch(e => { if (!controller.signal.aborted) setError(getErrorMessage(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [path, refresh]);
  return { data, error, loading };
}

export async function downloadResult(taskId: string, format: 'csv' | 'json') {
  const { data } = await api.get(`/api/v1/experiments/${taskId}/export?format=${format}`, { responseType: 'blob' });
  const url = URL.createObjectURL(data); const a = document.createElement('a');
  a.href = url; a.download = `GeneScope_${taskId}.${format}`; a.click(); URL.revokeObjectURL(url);
}

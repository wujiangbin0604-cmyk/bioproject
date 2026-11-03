export type Availability = 'available' | 'partial' | 'unavailable';

export interface Envelope<T> {
  status: Availability;
  source?: string | null;
  message?: string | null;
  data: T;
}

export interface ProjectMeta {
  name: string;
  subtitle: string;
  dataset: string;
  samples: number;
  features: number;
  development_samples: number;
  retrospective_holdout_samples: number;
  classes: Array<{ code: string; label: string }>;
  research_scope: string;
}

export interface DatasetSummary {
  dataset: { name: string; repository: string; samples: number; genes: number; classes: number; scope: string };
  classes: Array<{ code: string; label: string; sample_count: number; percentage: number }>;
  split: { development_samples: number; reserved_samples: number; development_percent: number; reserved_percent: number; random_state: number; stratified: boolean };
  development_class_counts: Array<{ code: string; label: string; sample_count: number; percentage: number }>;
  reserved_class_counts: Array<{ code: string; label: string; sample_count: number; percentage: number }>;
  quality: Record<string, number | boolean>;
  data_source_note: string;
  holdout_notice: string;
}

export interface ExperimentStatus {
  experiments: Array<{ id: string; name: string; status: 'available' | 'unavailable' | 'invalid'; verified_summary: boolean; message?: string }>;
  available_count: number;
  total_count: number;
  patient_level_outputs_exposed: boolean;
  heatmaps_available?: boolean;
}

export interface PerformanceData {
  records: Array<Record<string, string | number | null>>;
  aggregation_level: string;
  n_splits: number;
  n_repeats: number;
  random_state: number;
  statistical_note: string;
}

export interface StabilityData { records: Array<Record<string, string | number | null>>; n_subsamples: number; train_samples_per_subsample: number; random_state: number; statistical_note: string }
export interface GeneFrequencyData { records: Array<Record<string, string | number | null>>; page: number; page_size: number; total: number; anonymous_gene_ids: boolean; note: string }
export interface ModelComparisonData { models: Array<Record<string, string | number | null>>; test_scope: string; cv_scope: string; model_order_frozen: string[]; primary_model: string; test_sample_count: number }
export interface PerClassData { records: Array<Record<string, string | number | null>>; source_scope: string }
export interface ConfusionData { model: string; classes: Array<{ code: string; label: string }>; matrix: number[][]; sample_count: number; source_scope: string }
export interface HeatmapList { images: Array<{ method: string; name: string; status: string; url: string | null; scope: string; sample_order?: string; standardization?: string }> }
export interface FusionData { feature_overlap: Array<Record<string, unknown>>; fusion_performance: Array<Record<string, unknown>>; paired_comparisons: Array<Record<string, unknown>>; hard_voting: Array<Record<string, unknown>>; hard_voting_error_patterns: Array<Record<string, unknown>>; dynamic_arbitration: Array<Record<string, unknown>>; interpretation_note: string; event_note: string }
export interface ErrorAnalysis { shared_error_counts: Array<Record<string, string | number>>; relative_to_M1: Array<Record<string, string | number>>; patient_level_predictions_exposed: boolean; note: string }

export interface HealthData { api: string; results_available: boolean; model_available: boolean; model_name: string; model_version: string; model_unavailable_reason?: string | null; python_version: string }
export interface PredictionData { sample_id?: string | null; predicted_class: string; model_name: string; model_version: string; input_feature_count: number; selected_feature_count: number; input_columns_reordered: boolean; inference_status: 'success'; probability_output: false; interpretation_notice: string }

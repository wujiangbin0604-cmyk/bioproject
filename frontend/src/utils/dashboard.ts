import type { Result } from '../api/platform';

export const chartColors = ['#2678ef', '#19b5b0', '#9274db', '#60b3ee', '#e1ab60'];
export const algorithmOrder = ['linear_svc', 'logistic_regression', 'random_forest', 'rbf_svm'];
export function classColor(label: string, labels: string[]) {
  const pancan: Record<string, string> = { BRCA: chartColors[0], KIRC: chartColors[1], COAD: chartColors[2], LUAD: chartColors[3], PRAD: chartColors[4] };
  return pancan[label] ?? chartColors[Math.max(0, [...labels].sort().indexOf(label)) % chartColors.length];
}
export const formatCount = (value?: number | null) => value == null ? '—' : value.toLocaleString('zh-CN');
export const formatPercent = (value?: number | null) => value == null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(2)}%`;

// Precision/recall are the macro averages of recorded out-of-fold class reports.
// They must not be presented as fold means (only Accuracy and Macro-F1 are stored that way).
export function macroClassMetric(result: Result | undefined, metric: 'precision' | 'recall') {
  if (!result?.labels.length) return undefined;
  const values = result.labels.map(label => result.per_class[label]?.[metric]);
  if (values.some(value => typeof value !== 'number' || !Number.isFinite(value))) return undefined;
  return (values as number[]).reduce((sum, value) => sum + value, 0) / values.length;
}

import type { Config, Dataset } from '../api/platform';
export const defaultConfig: Config = { dataset_id: 'pancan', algorithms: ['linear_svc'], selection: 'anova', k: 50, folds: 5, seed: 42, repeats: 1, c: 1, gamma: 'scale', n_estimators: 100, max_depth: 10 };
export const K_VALUES = [20, 50, 100, 300, 500, 1000];
export const ALGORITHMS = ['linear_svc', 'logistic_regression', 'random_forest', 'rbf_svm'];
export function allowedK(dataset?: Dataset) { return K_VALUES.filter(k => dataset?.features == null || k <= dataset.features - Number(dataset.quality?.constant_features ?? 0)); }
export function validateExperiment(config: Config, dataset?: Dataset): Record<string, string> {
  const errors: Record<string, string> = {};
  if (dataset?.status !== 'ready') errors.dataset_id = '请选择已完成导入的数据集';
  if (!config.algorithms.length || config.algorithms.some(a => !ALGORITHMS.includes(a))) errors.algorithms = '至少选择一个已支持的分类模型';
  if (new Set(config.algorithms).size !== config.algorithms.length) errors.algorithms = '分类模型不能重复';
  if (!['none', 'anova', 'variance', 'coefficient'].includes(config.selection)) errors.selection = '请选择有效的特征方法';
  if (config.selection !== 'none' && !allowedK(dataset).includes(config.k)) errors.k = 'K必须来自可用候选值，且不超过有效特征数';
  if (!Number.isInteger(config.folds) || config.folds < 2 || config.folds > 10) errors.folds = 'CV折数必须为2–10的整数';
  if (dataset?.class_counts && Math.min(...Object.values(dataset.class_counts)) < config.folds) errors.folds = 'CV折数超过最小类别样本数';
  if (!Number.isInteger(config.repeats) || config.repeats < 1 || config.repeats > 5) errors.repeats = '重复轮数必须为1–5';
  if (config.folds * config.repeats * config.algorithms.length > 100) errors.repeats = '单任务最多100次模型折拟合，请减少模型或重复轮数';
  if (!Number.isInteger(config.seed) || config.seed < 0 || config.seed > 2147483647) errors.seed = '随机种子必须为0–2147483647的整数';
  if (!Number.isFinite(config.c) || config.c < .001 || config.c > 100) errors.c = 'C必须在0.001–100之间';
  if (!['scale', 'auto'].includes(config.gamma)) errors.gamma = 'gamma应为scale或auto';
  if (!Number.isInteger(config.n_estimators) || config.n_estimators < 10 || config.n_estimators > 300) errors.n_estimators = '树数量必须为10–300的整数';
  if (config.max_depth !== null && (!Number.isInteger(config.max_depth) || config.max_depth < 1 || config.max_depth > 30)) errors.max_depth = '最大深度必须为1–30或不限制';
  return errors;
}

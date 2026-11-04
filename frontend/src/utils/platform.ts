import { Message } from '@arco-design/web-react';
import { getErrorMessage } from '../api/client';
export const apiBase = '/api/v1';
export const metricNames: Record<string, string> = { macro_f1: 'Macro-F1', accuracy: 'Accuracy', balanced_accuracy: 'Balanced Accuracy', fit_seconds: '拟合与评价耗时' };
export const qualityNames: Record<string, string> = { finite: '表达值全部有效', duplicate_samples: '重复样本', duplicate_features: '重复特征', constant_features: '恒定特征', excluded_count: '排除样本', unique_groups: '独立供者', minimum: '最小表达值', maximum: '最大表达值', mean: '平均表达值' };
export const dateTime = (s: string) => new Date(s).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
export const datasetNames: Record<string, string> = { pancan: 'PANCAN RNA-Seq', gse4290: 'GSE4290 胶质瘤', gse44076: 'GSE44076 结直肠组织', gse45827: 'GSE45827 乳腺癌亚型' };
export function saveBlob(blob: Blob, name: string) { const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
export function reportError(error: unknown) { Message.error(getErrorMessage(error)); }
export async function copyText(text: string) { try { await navigator.clipboard.writeText(text); Message.success('已复制'); } catch { Message.error('当前浏览器无法访问剪贴板'); } }

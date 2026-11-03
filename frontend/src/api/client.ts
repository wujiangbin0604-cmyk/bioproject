import axios from 'axios';
import type { Envelope, PredictionData } from '../types/api';

export const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL ?? '', timeout: 30_000 });

export async function getEnvelope<T>(path: string, params?: Record<string, string | number | boolean | undefined>) {
  const response = await api.get<Envelope<T>>(path, { params });
  return response.data;
}

export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.error?.message;
    if (typeof detail === 'string') return detail;
    const validation = error.response?.data?.detail;
    if (typeof validation === 'string') return validation;
    if (error.response?.status === 401) return '登录验证已失效，请刷新页面后重新登录。';
    if (error.response?.status === 403) {
      if (typeof error.response.data === 'string' && error.response.data.includes('Live training is disabled')) {
        return '当前服务器尚未开放现场训练接口；冻结模型推理仍可使用。';
      }
      return '该请求被服务器访问规则拒绝，请确认通过正确的HTTPS地址访问。';
    }
    return error.response ? `请求失败（HTTP ${error.response.status}）` : '无法连接后端服务，请确认API已启动。';
  }
  return error instanceof Error ? error.message : '发生未知错误。';
}

export async function uploadPrediction(file: File): Promise<PredictionData> {
  const body = new FormData();
  body.append('file', file);
  const response = await api.post<{ status: 'success'; data: PredictionData }>('/api/v1/predict', body, {
    timeout: 60_000,
  });
  return response.data.data;
}

export async function downloadExample(): Promise<Blob> {
  const response = await api.get('/api/v1/predict/example', { responseType: 'blob' });
  return response.data as Blob;
}

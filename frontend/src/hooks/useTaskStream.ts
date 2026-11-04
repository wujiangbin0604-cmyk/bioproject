import { useEffect, useState } from 'react';
import type { Task } from '../api/platform';
import { terminal } from '../api/platform';
import { api, getErrorMessage } from '../api/client';

export function useTaskStream(taskId?: string) {
  const [state, setState] = useState<{ key?: string; task?: Task; error?: string; connected: boolean }>({ connected: false });
  useEffect(() => {
    if (!taskId) return;
    let active = true, busy = false, frame = 0, latest: Task | undefined, fallback: ReturnType<typeof setInterval> | undefined;
    const controller = new AbortController();
    setState({ key: taskId, connected: false });
    const publish = (task: Task, live = false) => {
      if (!active) return;
      setState(old => (old.task?.revision ?? -1) > (task.revision ?? 0) ? old : { key: taskId, task, connected: live || old.connected, error: live ? undefined : old.error });
    };
    const refresh = async () => {
      if (busy || !active) return;
      busy = true;
      try { const { data } = await api.get<Task>(`/api/v1/experiments/${taskId}`, { signal: controller.signal }); publish(data); if (terminal(data.status)) { clearInterval(fallback); stream.close(); } }
      catch (e) { if (!controller.signal.aborted) setState(old => ({ ...old, error: getErrorMessage(e) })); }
      finally { busy = false; }
    };
    void refresh();
    const stream = new EventSource(`${api.defaults.baseURL ?? ''}/api/v1/experiments/${taskId}/events`);
    stream.addEventListener('snapshot', event => {
      try {
        const task = JSON.parse((event as MessageEvent).data) as Task;
        if (terminal(task.status)) { cancelAnimationFrame(frame); frame = 0; publish(task, true); stream.close(); clearInterval(fallback); return; }
        latest = task;
        if (!frame) frame = requestAnimationFrame(() => { frame = 0; if (latest) publish(latest, true); });
      } catch { if (active) setState(old => ({ ...old, error: '任务事件格式无效，请刷新连接' })); }
    });
    stream.onopen = () => { if (active) setState(old => ({ ...old, connected: true, error: undefined })); clearInterval(fallback); fallback = undefined; };
    stream.onerror = () => {
      if (!active) return;
      setState(old => old.task && terminal(old.task.status) ? old : { ...old, connected: false, error: '实时连接暂时中断，正在重连并查询任务状态' });
      fallback ??= setInterval(() => void refresh(), 5000);
    };
    return () => { active = false; controller.abort(); stream.close(); cancelAnimationFrame(frame); clearInterval(fallback); };
  }, [taskId]);
  return { ...state, task: state.key === taskId ? state.task : undefined };
}

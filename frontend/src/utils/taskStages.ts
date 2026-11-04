import type { Task } from '../api/platform';
export type StageState = 'pending' | 'active' | 'complete' | 'stopped';
export function taskStages(task: Task): StageState[] {
  if (task.status === 'completed') return ['complete', 'complete', 'complete', 'complete', 'complete'];
  if (task.status === 'queued') return ['pending', 'pending', 'pending', 'pending', 'pending'];
  if (task.status === 'preparing') return ['active', 'pending', 'pending', 'pending', 'pending'];
  if (['failed', 'cancelled', 'cancel_requested'].includes(task.status)) return [task.completed_folds > 0 ? 'complete' : 'stopped', 'stopped', 'stopped', 'stopped', 'pending'];
  if (task.completed_folds === task.total_folds && task.total_folds > 0) return ['complete', 'complete', 'active', 'complete', 'active'];
  // The API publishes fold-level events. Selection, fit and evaluation form one observed CV stage;
  // the UI must not invent timestamps or claim an unobserved inner-pipeline step has completed.
  return ['complete', 'active', 'active', 'active', 'pending'];
}

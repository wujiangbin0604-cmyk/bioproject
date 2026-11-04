import { Icon } from './Icon';
import { statusNames } from '../../api/platform';
export function ExperimentStatus({ status, compact = false }: { status: string; compact?: boolean }) {
  return <span className={`experiment-status status-${status} ${compact ? 'status-compact' : ''}`}><span className="status-symbol">{['completed', 'ready'].includes(status) ? <Icon name="check" size={12} /> : <i />}</span>{statusNames[status] ?? status}</span>;
}

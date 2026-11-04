import type { ReactNode } from 'react';
import { Alert, Empty, Skeleton } from '@arco-design/web-react';
import { Icon } from './Icon';
export function LoadingSkeleton({ rows = 3 }: { rows?: number }) { return <div className="loading-skeleton" role="status" aria-label="正在加载"><Skeleton animation text={{ rows, width: ['80%', '95%', '68%'] }} /></div>; }
export function EmptyState({ title = '尚无实验结果', description, action }: { title?: string; description?: ReactNode; action?: ReactNode }) { return <div className="empty-state"><Empty icon={<Icon name="flask" size={40} />} description={<><strong>{title}</strong>{description && <p>{description}</p>}</>} />{action}</div>; }
export function ErrorState({ message }: { message?: string | null }) { return message ? <Alert className="error-state" type="error" content={message} closable={false} /> : null; }

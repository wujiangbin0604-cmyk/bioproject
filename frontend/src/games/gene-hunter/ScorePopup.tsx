import type { CSSProperties } from 'react';
import type { HitFeedback } from './types';
import { usePreferences } from '../../hooks/usePreferences';

export function ScorePopup({ feedback, x }: { feedback: HitFeedback; x: number }) {
  const { reduced } = usePreferences();
  return <span key={feedback.id} className={`gh-hit-effect gh-effect-${feedback.kind}`} style={{ left: `${x}%` }} aria-hidden="true">
    {!reduced && feedback.kind === 'high' && <span className="gh-particles">{Array.from({ length: 8 }, (_, i) => <i key={i} style={{ '--angle': `${i * 45}deg` } as CSSProperties} />)}</span>}
    <span className="gh-score-popup">{feedback.points ? `+${feedback.points.toLocaleString()}` : '继续观察'}<small>{feedback.geneId}</small></span>
  </span>;
}

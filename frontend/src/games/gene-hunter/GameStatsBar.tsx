import { Icon } from '../../components/ui/Icon';
import { ComboBadge } from './ComboBadge';
import type { GeneHunterLevel, HunterState } from './types';

export function GameStatsBar({ state, level, totalLevels, growthLevel }: { state: HunterState; level: GeneHunterLevel; totalLevels: number; growthLevel: number }) {
  const seconds = Math.ceil(state.remainingMs / 1000), hits = Object.values(state.selections).filter(s => s.kind === 'high').length;
  return <div className="gh-stats-wrap">
    <div className="gh-round-line"><span className="gh-level-badge">Lv.{growthLevel}</span><strong>关卡 {state.levelIndex + 1} / {totalLevels}<span>{level.title}</span></strong>
      <div className="gh-level-dots" aria-label={`当前第${state.levelIndex + 1}关，共${totalLevels}关`}>{Array.from({ length: totalLevels }, (_, i) => <i key={i} data-status={i < state.levelIndex ? 'done' : i === state.levelIndex ? 'current' : 'pending'} />)}</div>
    </div>
    <div className="gh-stats">
      <div className={`gh-stat gh-clock ${seconds <= 10 && state.phase === 'playing' ? 'gh-urgent' : ''}`}><span className="gh-stat-icon"><Icon name="timer" size={26} /></span><div><span>剩余时间</span><strong role="timer" aria-label="剩余时间" data-testid="timer">{String(Math.floor(seconds / 60)).padStart(2, '0')}:{String(seconds % 60).padStart(2, '0')}</strong></div></div>
      <div className="gh-stat gh-score"><span className="gh-stat-icon"><Icon name="trophy" size={26} /></span><div><span>累计得分</span><strong data-testid="total-score">{state.totalScore.toLocaleString()}</strong></div></div>
      <ComboBadge combo={state.combo} />
      <div className="gh-stat gh-target"><span className="gh-stat-icon"><Icon name="compare" size={26} /></span><div><span>本关目标</span><strong>{hits}<small> / {level.targetHits} 个</small></strong></div></div>
    </div>
  </div>;
}

import { GlassCard } from '../../components/ui/GlassCard';
import { Icon } from '../../components/ui/Icon';
import type { GeneHunterLevel, HunterState } from './types';

export function MissionCard({ level, state }: { level: GeneHunterLevel; state: HunterState }) {
  const hits = Object.values(state.selections).filter(s => s.kind === 'high').length;
  return <GlassCard className="gh-mission" title={<><Icon name="target" /> 当前任务</>} extra={<span className="gh-pill">第 {level.levelId} 关</span>}>
    <h3>在 <em>{level.timeLimit} 秒</em>内，<br />找出最能区分类别的关键基因</h3>
    <p>{level.description}</p>
    <div className="gh-mission-progress"><span>关键特征命中 <b>{hits} / {level.targetHits}</b></span><div role="progressbar" aria-label="本关关键特征命中" aria-valuenow={hits} aria-valuemin={0} aria-valuemax={level.targetHits}><i style={{ width: `${Math.min(100, hits / level.targetHits * 100)}%` }} /></div></div>
    <ul><li><Icon name="check" size={14} /> 观察两组样本的表达差异</li><li><Icon name="check" size={14} /> 点击整行，确认你的选择</li><li><Icon name="check" size={14} /> 命中 {level.targetHits} 个高价值特征即达标</li></ul>
    <div className="gh-mission-note"><Icon name="flask" size={15} /> 合成表达数据 · 判别分数为教学预设</div>
  </GlassCard>;
}

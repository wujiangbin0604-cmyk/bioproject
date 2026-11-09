import { GlassCard } from '../../components/ui/GlassCard';
import { Icon } from '../../components/ui/Icon';
import type { GeneHunterLevel, HunterState } from './types';

export function RoundResultCard({ level, state }: { level: GeneHunterLevel; state: HunterState }) {
  const revealed = state.phase === 'review' || state.phase === 'complete';
  const result = revealed ? state.history.at(-1) : undefined;
  const feedback = state.feedback;
  return <GlassCard className={`gh-result ${revealed ? 'gh-result-revealed' : ''}`} title={<><Icon name={revealed ? 'check' : 'features'} /> 本回合结果</>}
    extra={<span className={`gh-pill ${revealed ? 'gh-pill-mint' : ''}`}>{revealed ? result && result.hits >= level.targetHits ? '已达标' : '已结算' : '等待揭晓'}</span>}>
    {result ? <>
      <div className="gh-round-summary" role="status"><div className="gh-stars" aria-label={`${result.stars} 星，共3星`}>{[1, 2, 3].map(i => <Icon key={i} name="star" size={23} className={i <= result.stars ? 'gh-star-earned' : ''} />)}</div><strong>找到 {result.hits} / {level.targetHits} 个关键特征</strong><span>本关 +{result.score.toLocaleString()} · 最高 {result.bestCombo} 连击</span></div>
      <div className="gh-top-title">本关参考排名 <span>按教学预设分数 · Top 5</span></div>
      <ol className="gh-top-list">{level.topRankedGenes.map((id, i) => {
        const gene = level.genes.find(g => g.geneId === id)!, hit = !!result.selections[id];
        return <li key={id}><span className={`gh-rank gh-rank-${i + 1}`}>{i + 1}</span><b>{id}</b><div className="gh-rank-track"><i style={{ width: `${gene.discriminativeScore * 100}%` }} /></div><span>{gene.discriminativeScore.toFixed(2)}</span><span className={`gh-hit-status ${hit ? 'gh-is-hit' : ''}`}>{hit ? '命中' : '遗漏'}</span></li>;
      })}</ol>
      <p className="gh-learning-note">{result.hits >= level.targetHits ? '观察很敏锐！下一关试着留意表达方向相反的特征。' : '回看遗漏的行：两组颜色是否明显不同？也要留意组内波动。'}</p>
    </> : <>
      <div className="gh-locked-ranking"><span className="gh-ranking-icon"><Icon name="compare" size={32} /></span><strong>先用你的观察力做出选择</strong><p>时间结束或提交本关后，<br />揭晓 Top 5 并对比命中情况。</p><div aria-hidden="true">{[78, 63, 46].map((width, i) => <span key={i}><i>{i + 1}</i><b style={{ width: `${width}%` }} /></span>)}</div></div>
      <div className={`gh-last-feedback ${feedback ? `gh-feedback-${feedback.kind}` : ''}`} role="status" aria-live="polite" aria-atomic="true">{feedback ? <><Icon name={feedback.kind === 'high' ? 'check' : 'info'} size={16} /><span><b>{feedback.geneId}</b> · {feedback.kind === 'high' ? `关键特征 +${feedback.points}` : feedback.kind === 'medium' ? '中等价值 +300，连击重置' : '组间差异较弱，连击重置'}</span></> : <><Icon name="info" size={16} /><span>选择后，这里会显示即时反馈</span></>}</div>
    </>}
  </GlassCard>;
}

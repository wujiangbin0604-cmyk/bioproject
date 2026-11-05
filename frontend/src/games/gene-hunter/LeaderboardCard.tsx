import { GlassCard } from '../../components/ui/GlassCard';
import { Icon } from '../../components/ui/Icon';

const leaders = [
  { name: '生信小白进阶', score: 32800, avatar: '研', color: '#a3b9f6' },
  { name: 'GeneHunter', score: 31600, avatar: 'G', color: '#b8a4e9' },
  { name: '细胞观察员', score: 30940, avatar: '细', color: '#84c9c1' },
  { name: 'BioCoder', score: 29820, avatar: 'B', color: '#92bde8' },
  { name: '表达探索者', score: 28500, avatar: '探', color: '#ccb2de' },
];

export function LeaderboardCard({ bestScore }: { bestScore: number }) {
  return <GlassCard id="gh-leaderboard" className="gh-leaderboard" title={<><Icon name="trophy" /> 本周排行榜</>} extra={<span className="gh-pill">示例榜单</span>}>
    <ol>{leaders.map((leader, i) => <li key={leader.name}><span className={`gh-rank gh-rank-${i + 1}`}>{i + 1}</span><span className="gh-avatar" style={{ background: leader.color }}>{leader.avatar}</span><span>{leader.name}</span><b>{leader.score.toLocaleString()}</b></li>)}</ol>
    <div className="gh-personal-best"><Icon name="user" size={16} /><span>我的完整挑战最佳</span><b>{bestScore ? bestScore.toLocaleString() : '待挑战'}</b></div>
    <p className="gh-muted">榜单为模拟示例；个人记录仅保存在当前浏览器。</p>
  </GlassCard>;
}

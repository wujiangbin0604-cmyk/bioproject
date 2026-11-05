import { GlassCard } from '../../components/ui/GlassCard';
import { Icon } from '../../components/ui/Icon';

export function growthLevel(stars: number) { return stars >= 15 ? 4 : stars >= 9 ? 3 : stars >= 3 ? 2 : 1; }
export function GrowthCard({ stars }: { stars: number }) {
  const level = growthLevel(stars), next = [3, 9, 15, 15][level - 1];
  return <GlassCard className="gh-growth" title={<><Icon name="gift" /> 奖励与成长</>} extra={<span className="gh-pill">Lv.{level}</span>}>
    <div className="gh-growth-badges">{['入门', '熟练', '进阶', '高手'].map((label, i) => <div key={label} className={i + 1 <= level ? 'gh-unlocked' : ''}><span><Icon name={i === 3 ? 'trophy' : 'star'} size={25} /></span><b>Lv.{i + 1}</b><small>{label}</small></div>)}</div>
    <div className="gh-growth-progress"><span>关卡最佳星数 <b>{stars} / 15 <Icon name="star" size={14} /></b></span><div role="progressbar" aria-label="成长星数" aria-valuenow={stars} aria-valuemin={0} aria-valuemax={15}><i style={{ width: `${stars / 15 * 100}%` }} /></div></div>
    <div className="gh-reward"><Icon name="gift" size={21} /><div><b>{level === 4 ? '关键特征猎手已解锁！' : `再获 ${next - stars} 星，解锁 Lv.${level + 1}`}</b><p>每关保留最佳星数，重玩可提升成绩。</p></div></div>
  </GlassCard>;
}

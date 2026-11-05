import { GlassCard } from '../../components/ui/GlassCard';
import { Icon } from '../../components/ui/Icon';

const steps = [
  { title: '观察组间差异', text: '左右各是一组样本。寻找组内颜色相近、两组颜色不同的基因行。', icon: 'grid' as const },
  { title: '点击关键基因', text: '点击基因名或色块选择整行。高价值 +800，中等 +300，低价值 +0。', icon: 'target' as const },
  { title: '连续命中加成', text: '高价值 2 连击 ×1.2，3 连击 ×1.5，4 连击起 ×2。其余选择重置连击。', icon: 'flame' as const },
  { title: '对比特征排名', text: '提交或时间结束后对照 Top 5。命中 1 / 3 / 5 个分别获得 1 / 2 / 3 星。', icon: 'compare' as const },
];

export function GameGuideSection() {
  return <GlassCard className="gh-guide" title={<><Icon name="game" /> 玩法与交互流程</>} extra={<span className="gh-muted">4 步上手</span>}>
    <div className="gh-guide-grid">{steps.map((step, i) => <article key={step.title}><div className="gh-guide-step"><span>{i + 1}</span><h3>{step.title}</h3></div><p>{step.text}</p><div className={`gh-guide-illustration gh-guide-art-${i}`} aria-hidden="true"><Icon name={step.icon} size={30} />{i === 0 ? <div className="gh-mini-heatmap">{Array.from({ length: 12 }, (_, j) => <i key={j} />)}</div> : i === 1 ? <b>KRT19 <span>+800</span></b> : i === 2 ? <b>Combo <span>×3</span></b> : <b>Top 5 <span>揭晓</span></b>}</div></article>)}</div>
  </GlassCard>;
}

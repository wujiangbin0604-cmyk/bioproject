import type { ReactNode } from 'react';
import { Button, Tag } from '@arco-design/web-react';
import { Link } from 'react-router-dom';
import { Icon } from '../ui/Icon';
import type { IconName } from '../ui/Icon';
import { GlassCard } from '../ui/GlassCard';
import { formatCount } from '../../utils/dashboard';

export function ChallengeEntryCard() {
  return <section className="challenge-entry" aria-labelledby="challenge-title">
    <span className="challenge-icon"><Icon name="game" size={28} /></span>
    <div className="challenge-copy"><h2 id="challenge-title">试试你的基因识别能力！</h2><p>观察基因表达热图中的类别差异，寻找关键特征，体验统计判别与生物信息学分析。</p>
      <div className="challenge-tags"><Tag color="arcoblue">新手友好</Tag><Tag color="cyan">基因热图</Tag><Tag color="purple">特征选择</Tag><span>基因猎手 · 合成数据教学</span></div>
    </div>
    <div className="challenge-graphic" aria-hidden="true"><div className="mini-heatmap">{Array.from({ length: 28 }, (_, i) => <i key={i} className={`heat-cell-${(i * 3 + Math.floor(i / 7)) % 5}`} />)}</div><span className="challenge-lens"><Icon name="search" size={25} /></span></div>
    <div className="challenge-action"><Link to="/games/gene-hunter"><Button type="primary">开始挑战 <Icon name="arrow" size={15} /></Button></Link><Link to="/presentation">查看学习指南</Link></div>
  </section>;
}

export function SummaryCard({ label, value, detail, icon, tone, to, extra, loading }: {
  label: string; value?: number | null; detail: ReactNode; icon: IconName; tone: string; to: string; extra?: ReactNode; loading?: boolean;
}) {
  return <Link to={to} className={`summary-card tone-${tone}`} aria-label={`${label}：${formatCount(value)}`}>
    <span className="summary-icon"><Icon name={icon} size={25} /></span><div className="summary-copy"><span>{label}</span><strong aria-busy={loading}>{loading ? <i className="number-skeleton" /> : formatCount(value)}{extra}</strong><small>{detail}</small></div>
    <Icon name="chevron" size={15} className="summary-chevron" />
  </Link>;
}

const steps: { title: string; hint: string; icon: IconName; to: string }[] = [
  { title: '数据集管理', hint: '导入与质量检查', icon: 'database', to: '/datasets' },
  { title: '特征选择', hint: '筛选关键表达特征', icon: 'features', to: '/features' },
  { title: '模型训练', hint: '配置算法与交叉验证', icon: 'flask', to: '/lab' },
  { title: '结果分析', hint: '比较指标与稳定性', icon: 'compare', to: '/comparison' },
  { title: '模型预测', hint: '验证单样本表达', icon: 'target', to: '/predict' },
  { title: '游戏化学习', hint: '理解特征判别思路', icon: 'game', to: '/games/gene-hunter' },
];
export function WorkflowCard() {
  return <GlassCard className="dashboard-workflow" title={<><Icon name="features" /> 项目工作流程</>} subtitle="Project Workflow" extra={<Link to="/lab" className="quiet-link">创建新实验 <Icon name="arrow" size={14} /></Link>}>
    <ol className="research-workflow">{steps.map((step, index) => <li key={step.title}><Link to={step.to}><span className="workflow-node"><Icon name={step.icon} size={21} /><small>{index + 1}</small></span><span><strong>{step.title}</strong><small>{step.hint}</small></span></Link>{index < steps.length - 1 && <Icon name="chevron" size={14} />}</li>)}</ol>
  </GlassCard>;
}

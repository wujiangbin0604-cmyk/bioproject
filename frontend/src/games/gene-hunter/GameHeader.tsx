import { Tag } from '@arco-design/web-react';
import { Icon } from '../../components/ui/Icon';
import { HeroDNA } from '../../components/visuals/AnimatedDNA';

export function GameHeader({ onHelp }: { onHelp: () => void }) {
  return <header className="gh-hero">
    <div className="gh-hero-copy">
      <div className="gh-hero-label"><Tag color="arcoblue"><Icon name="game" size={14} /> 生物信息学游戏</Tag><span>Gene Hunter</span></div>
      <h1>基因猎手：寻找关键特征</h1>
      <p>在动态基因表达热图中，快速识别最能区分不同类别的关键基因，体验特征选择的核心思路。</p>
      <div className="gh-hero-meta"><span><Icon name="check" size={14} /> 5 关渐进挑战</span><span><Icon name="check" size={14} /> 合成数据教学</span><button onClick={onHelp}><Icon name="info" size={14} /> 第一次玩？查看指南</button></div>
    </div>
    <HeroDNA />
    <div className="gh-hero-seal" aria-hidden="true"><Icon name="target" size={32} /><span>观察差异<br /><b>发现关键</b></span></div>
  </header>;
}

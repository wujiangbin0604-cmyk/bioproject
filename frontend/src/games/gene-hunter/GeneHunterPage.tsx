import { useEffect, useRef, useState } from 'react';
import { Modal } from '@arco-design/web-react';
import { GlassCard } from '../../components/ui/GlassCard';
import { Icon } from '../../components/ui/Icon';
import { GameHeader } from './GameHeader';
import { GameStatsBar } from './GameStatsBar';
import { GeneHeatmapBoard } from './GeneHeatmapBoard';
import { MissionCard } from './MissionCard';
import { RoundResultCard } from './RoundResultCard';
import { LeaderboardCard } from './LeaderboardCard';
import { GameGuideSection } from './GameGuideSection';
import { GrowthCard, growthLevel } from './GrowthCard';
import { useGeneHunterGame } from './useGeneHunterGame';
import './gene-hunter.less';

export default function GeneHunterPage() {
  const game = useGeneHunterGame(), { state, level, progress } = game;
  const [helpOpen, setHelpOpen] = useState(false);
  const summaryRef = useRef<HTMLDivElement>(null);
  const stars = Object.values(progress.levelStars).reduce((sum, value) => sum + value, 0);
  useEffect(() => {
    const previous = document.title;
    document.title = '基因猎手：寻找关键特征 | GeneScope 2.0';
    return () => { document.title = previous; };
  }, []);
  useEffect(() => { if (state.phase === 'complete') summaryRef.current?.focus(); }, [state.phase]);
  return <div className="gh-page workspace-page">
    <nav className="gh-breadcrumb" aria-label="面包屑"><Icon name="game" size={15} /><span>学习与游戏</span><Icon name="chevron" size={12} /><b>基因猎手</b></nav>
    <GameHeader onHelp={() => setHelpOpen(true)} />
    {state.phase === 'complete' && <div ref={summaryRef} tabIndex={-1} className="gh-complete" role="status"><span className="gh-complete-icon"><Icon name="trophy" size={34} /></span><div><h2>挑战完成，你已走过全部 5 关！</h2><p>累计 {state.totalScore.toLocaleString()} 分 · 本次 {state.history.reduce((sum, r) => sum + r.stars, 0)} / 15 星 · 找到 {state.history.reduce((sum, r) => sum + r.hits, 0)} 个关键特征</p></div><div className="gh-complete-rounds">{state.history.map(r => <span key={r.levelId}>第 {r.levelId} 关 <b>{r.stars} ★</b></span>)}</div></div>}
    <div className="gh-game-layout">
      <GlassCard className="gh-arena"><GameStatsBar state={state} level={level} totalLevels={game.totalLevels} growthLevel={growthLevel(stars)} /><GeneHeatmapBoard level={level} state={state} onSelect={game.selectGene} onStart={game.start} onFinish={game.finish} onNext={game.next} onRestart={game.restart} /></GlassCard>
      <aside className="gh-game-aside" aria-label="任务与回合反馈"><MissionCard level={level} state={state} /><RoundResultCard level={level} state={state} /></aside>
    </div>
    <GameGuideSection />
    <div className="gh-community"><LeaderboardCard bestScore={progress.bestScore} /><GrowthCard stars={stars} /><GlassCard className="gh-science" title={<><Icon name="dna" /> 从游戏走向特征选择</>}><p>有用的特征能帮助区分类别。组间差异与组内波动，都是观察表达热图时的重要线索。</p><p>真实分析还需在训练数据内选择特征，通过独立验证评估泛化能力，并考虑基因间冗余与生物学背景。</p><div><Icon name="flask" size={20} /><span>观察 → 选择 → 验证<br /><b>让每一次选择，都有依据。</b></span></div></GlassCard></div>
    <p className="gh-disclaimer"><Icon name="info" size={16} /> 本游戏使用合成教学数据，帮助理解基因表达差异与特征选择的基本思想。游戏分数与预设判别分数仅用于交互式学习体验，不代表科研指标或临床诊断结论。</p>
    <Modal title="基因猎手 · 新手指南" visible={helpOpen} onCancel={() => setHelpOpen(false)} footer={null} style={{ width: 'min(560px, 94vw)' }}>
      <div className="gh-help"><p>每行是一个基因，每列是一个样本。浅蓝代表较低表达，淡紫代表较高表达；颜色表示标准化后的相对值。</p><p>优先寻找同一组内颜色相近、两组之间明显不同的行。两种表达方向都可能成为有用特征。</p><p>点击“开始挑战”开始计时，点击基因整行作答，每行只能选择一次。高价值基因（预设分数 ≥ 0.80）获得 800 基础分，中等价值（0.50–0.79）获得 300 分，低价值（&lt; 0.50）获得 0 分。</p><p>连续选择高价值基因会触发 1.2 / 1.5 / 2.0 倍加成。时间结束或主动提交后揭晓排名。进入下一关后可先观察，再开始计时。</p><p>倒计时期间查看指南也会继续计时。星数和完整挑战最佳成绩保存在当前浏览器中。</p></div>
    </Modal>
  </div>;
}

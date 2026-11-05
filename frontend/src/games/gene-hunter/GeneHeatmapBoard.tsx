import { Button } from '@arco-design/web-react';
import { Icon } from '../../components/ui/Icon';
import { GeneRow } from './GeneRow';
import type { GeneHunterLevel, HunterState } from './types';

export function GeneHeatmapBoard({ level, state, onSelect, onStart, onFinish, onNext, onRestart }: {
  level: GeneHunterLevel; state: HunterState; onSelect: (id: string) => void; onStart: () => void; onFinish: () => void; onNext: () => void; onRestart: () => void;
}) {
  const revealed = state.phase === 'review' || state.phase === 'complete';
  return <section className="gh-board" aria-labelledby="gh-heatmap-title">
    <header className="gh-board-heading"><div><h2 id="gh-heatmap-title"><Icon name="grid" size={18} /> 基因表达热图</h2><span>行：基因 / 列：样本</span></div><div className="gh-legend"><span>低</span><i /><span>高</span><small>标准化表达值</small></div></header>
    <p className="gh-mobile-scroll-hint"><Icon name="arrow" size={12} /> 左右滑动热图，对比两组样本；基因名固定在左侧。</p>
    <div className="gh-board-scroll" tabIndex={0} role="region" aria-label="基因热图，可横向滚动">
      <div className="gh-board-table" key={level.levelId}>
        <div className="gh-table-heading"><span>基因 Gene ID</span><div className="gh-sample-groups"><span>{level.classAName} <small>n = 8</small></span><span>{level.classBName} <small>n = 8</small></span></div><span>{revealed ? '判别分数' : '反馈'}</span></div>
        <div className="gh-sample-names"><span /><div>{Array.from({ length: 16 }, (_, i) => <span key={i}>{i < 8 ? 'A' : 'B'}{i % 8 + 1}</span>)}</div><span /></div>
        {level.genes.map(gene => <GeneRow key={gene.geneId} gene={gene} selection={state.selections[gene.geneId]} feedback={state.feedback?.geneId === gene.geneId ? state.feedback : null} disabled={state.phase !== 'playing'} revealed={revealed} onSelect={onSelect} />)}
      </div>
    </div>
    <div className="gh-board-hint"><Icon name="info" size={14} /><span>{state.phase === 'ready' ? '先观察热图，准备好后开始计时。点击基因名或任意色块选择整行。' : revealed ? '算法已揭晓：对照右侧排名，回看你选择的特征。' : '寻找组内相近、组间差异明显的行。每个基因仅计分一次。'}</span></div>
    <footer className="gh-board-actions">
      {state.phase === 'ready' ? <Button type="primary" size="large" className="gradient-button" icon={<Icon name="play" size={17} />} onClick={onStart}>{state.levelIndex === 0 ? '开始挑战' : `开始第 ${state.levelIndex + 1} 关`}</Button>
        : state.phase === 'playing' ? <Button type="primary" size="large" className="gradient-button" icon={<Icon name="check" size={17} />} onClick={onFinish}>提交本关 · 揭晓排名</Button>
          : state.phase === 'review' ? <Button type="primary" size="large" className="gradient-button" icon={<Icon name="arrow" size={17} />} onClick={onNext}>{state.levelIndex === 4 ? '查看挑战总结' : '进入下一关'}</Button>
            : <Button type="primary" size="large" className="gradient-button" icon={<Icon name="refresh" size={17} />} onClick={onRestart}>再挑战一次</Button>}
      <a href="#gh-leaderboard"><Icon name="trophy" size={16} /> 查看排行</a>
      <span className="gh-round-score">本关得分 <b>{state.roundScore.toLocaleString()}</b></span>
    </footer>
  </section>;
}

import { memo, useState } from 'react';
import { Tooltip } from '@arco-design/web-react';
import { Icon } from '../../components/ui/Icon';
import type { GeneSelection, HitFeedback, HunterGene } from './types';
import { ScorePopup } from './ScorePopup';

export function expressionColor(value: number) {
  const strength = Math.min(1, Math.abs(value) / 2);
  const low = [128, 183, 241], high = [192, 142, 231];
  const color = value < 0 ? low : high;
  return `rgb(${color.map(channel => Math.round(248 + (channel - 248) * strength)).join(',')})`;
}

export const GeneRow = memo(function GeneRow({ gene, selection, feedback, disabled, revealed, onSelect }: {
  gene: HunterGene; selection?: GeneSelection; feedback: HitFeedback | null; disabled: boolean; revealed: boolean; onSelect: (id: string) => void;
}) {
  const [clickX, setClickX] = useState(60);
  const kindLabel = selection?.kind === 'high' ? '关键特征' : selection?.kind === 'medium' ? '中等价值' : '低判别力';
  return <div className={`gh-gene-row ${selection ? `gh-selected gh-selected-${selection.kind}` : ''}`}>
    <button type="button" className="gh-row-button" disabled={disabled || !!selection} aria-label={`选择基因 ${gene.geneId}${selection ? `，已选择，${kindLabel}` : ''}`}
      data-gene={gene.geneId} data-selected={!!selection} onClick={event => {
        const box = event.currentTarget.getBoundingClientRect();
        setClickX(event.detail === 0 ? 60 : Math.min(90, Math.max(20, (event.clientX - box.left) / box.width * 100)));
        onSelect(gene.geneId);
      }}>
      <span className="gh-gene-label"><span className="gh-selection-mark">{selection ? <Icon name={selection.kind === 'low' ? 'close' : 'check'} size={12} /> : null}</span><b>{gene.geneId}</b></span>
      <span className="gh-expression-cells">{gene.expressionValues.flat().map((value, i) => <Tooltip key={i} position="top" mini content={<span>{gene.geneId} · {i < 8 ? 'A' : 'B'}{i % 8 + 1} · 表达值 {value.toFixed(2)}</span>}><span className="gh-cell" style={{ backgroundColor: expressionColor(value) }} /></Tooltip>)}</span>
      <span className="gh-gene-outcome">{revealed ? gene.discriminativeScore.toFixed(2) : selection ? selection.points ? `+${selection.points}` : '观察' : '—'}</span>
    </button>
    {feedback?.geneId === gene.geneId && <ScorePopup feedback={feedback} x={clickX} />}
  </div>;
});

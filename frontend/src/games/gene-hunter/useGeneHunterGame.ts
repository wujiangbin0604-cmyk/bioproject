import { useCallback, useEffect, useReducer, useState } from 'react';
import { geneHunterLevels } from '../../mock/geneHunterLevels';
import { readStored, writeStored } from '../../hooks/usePreferences';
import { initialHunterState, mergeProgress, parseProgress, reduceHunterGame } from './gameEngine';
import type { GeneHunterLevel, HunterState } from './types';

export function useGeneHunterGame(levels: readonly GeneHunterLevel[] = geneHunterLevels) {
  const [state, dispatch] = useReducer((state: HunterState, action: Parameters<typeof reduceHunterGame>[1]) => reduceHunterGame(state, action, levels), levels[0], initialHunterState);
  const [progress, setProgress] = useState(() => parseProgress(readStored<unknown>('genescope-gene-hunter-v1', null)));
  useEffect(() => {
    if (state.phase !== 'playing') return;
    const tick = () => dispatch({ type: 'tick', now: Date.now() });
    const timer = window.setInterval(tick, 100);
    document.addEventListener('visibilitychange', tick);
    return () => { window.clearInterval(timer); document.removeEventListener('visibilitychange', tick); };
  }, [state.phase, state.levelIndex]);
  useEffect(() => {
    if (!state.history.length) return;
    setProgress(previous => mergeProgress(previous, state));
  }, [state.history, state.phase]); // Score is finalized when history or phase changes.
  useEffect(() => { writeStored('genescope-gene-hunter-v1', progress); }, [progress]);
  const selectGene = useCallback((geneId: string) => dispatch({ type: 'select', geneId, now: Date.now() }), []);
  return { state, progress, level: levels[state.levelIndex], totalLevels: levels.length, selectGene,
    start: () => dispatch({ type: 'start', now: Date.now() }), finish: () => dispatch({ type: 'finish', now: Date.now() }),
    next: () => dispatch({ type: 'next' }), restart: () => dispatch({ type: 'restart' }) };
}

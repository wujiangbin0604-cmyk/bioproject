import type { GeneHunterLevel, HitKind, HunterState, HunterProgress } from './types';

export type HunterAction = { type: 'start' | 'tick' | 'finish'; now: number }
  | { type: 'select'; geneId: string; now: number }
  | { type: 'next' }
  | { type: 'restart' };

export function hitKind(score: number): HitKind { return score >= .8 ? 'high' : score >= .5 ? 'medium' : 'low'; }
export function comboMultiplier(combo: number) { return combo >= 4 ? 2 : combo === 3 ? 1.5 : combo === 2 ? 1.2 : 1; }
export function initialHunterState(level: GeneHunterLevel): HunterState {
  return { phase: 'ready', levelIndex: 0, deadline: null, remainingMs: level.timeLimit * 1000, totalScore: 0,
    roundScore: 0, combo: 0, bestCombo: 0, selections: {}, feedback: null, history: [] };
}

function finishRound(state: HunterState, level: GeneHunterLevel): HunterState {
  if (state.phase !== 'playing') return state;
  const hits = Object.values(state.selections).filter(s => s.kind === 'high').length;
  const stars = hits >= level.targetHits ? 3 : hits >= Math.ceil(level.targetHits * .6) ? 2 : hits > 0 ? 1 : 0;
  return { ...state, phase: 'review', deadline: null, remainingMs: 0, feedback: null,
    history: [...state.history, { levelId: level.levelId, score: state.roundScore, hits, stars,
      bestCombo: state.bestCombo, selections: state.selections }] };
}

/** All score mutations are atomic and checked against the absolute deadline. */
export function reduceHunterGame(state: HunterState, action: HunterAction, levels: readonly GeneHunterLevel[]): HunterState {
  const level = levels[state.levelIndex];
  if (action.type === 'restart') return initialHunterState(levels[0]);
  if (action.type === 'start') return state.phase === 'ready'
    ? { ...state, phase: 'playing', deadline: action.now + level.timeLimit * 1000, remainingMs: level.timeLimit * 1000 } : state;
  if (action.type === 'next') {
    if (state.phase !== 'review') return state;
    if (state.levelIndex === levels.length - 1) return { ...state, phase: 'complete' };
    return { ...initialHunterState(levels[state.levelIndex + 1]), levelIndex: state.levelIndex + 1,
      totalScore: state.totalScore, history: state.history };
  }
  if (state.phase !== 'playing' || state.deadline === null) return state;
  if (action.now >= state.deadline || action.type === 'finish') return finishRound(state, level);
  if (action.type === 'tick') return { ...state, remainingMs: Math.max(0, state.deadline - action.now) };
  if (action.type !== 'select' || Object.hasOwn(state.selections, action.geneId)) return state;
  const gene = level.genes.find(g => g.geneId === action.geneId);
  if (!gene) return state;
  const kind = hitKind(gene.discriminativeScore), combo = kind === 'high' ? state.combo + 1 : 0;
  const points = kind === 'high' ? Math.round(800 * comboMultiplier(combo)) : kind === 'medium' ? 300 : 0;
  return { ...state, totalScore: state.totalScore + points, roundScore: state.roundScore + points, combo,
    bestCombo: Math.max(state.bestCombo, combo), remainingMs: state.deadline - action.now,
    selections: { ...state.selections, [gene.geneId]: { kind, points, combo } },
    feedback: { id: Object.keys(state.selections).length + 1, geneId: gene.geneId, kind, points, combo } };
}

export const emptyProgress: HunterProgress = { version: 1, bestScore: 0, levelStars: {} };
export function parseProgress(value: unknown): HunterProgress {
  if (!value || typeof value !== 'object') return emptyProgress;
  const saved = value as Partial<HunterProgress>;
  const bestScore = typeof saved.bestScore === 'number' && Number.isFinite(saved.bestScore) && saved.bestScore >= 0 ? Math.floor(saved.bestScore) : 0;
  const levelStars = Object.fromEntries(Object.entries(saved.levelStars && typeof saved.levelStars === 'object' ? saved.levelStars : {})
    .filter(([id, stars]) => /^[1-5]$/.test(id) && Number.isInteger(stars) && stars >= 0 && stars <= 3));
  return saved.version === 1 ? { version: 1, bestScore, levelStars } : emptyProgress;
}
export function mergeProgress(progress: HunterProgress, state: HunterState): HunterProgress {
  const levelStars = { ...progress.levelStars };
  for (const result of state.history) levelStars[result.levelId] = Math.max(levelStars[result.levelId] ?? 0, result.stars);
  // Only a fully submitted five-round run qualifies as a personal score record.
  return { version: 1, levelStars, bestScore: state.phase === 'complete' ? Math.max(progress.bestScore, state.totalScore) : progress.bestScore };
}

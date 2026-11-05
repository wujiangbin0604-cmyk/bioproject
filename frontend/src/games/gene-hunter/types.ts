export type HitKind = 'high' | 'medium' | 'low';
export type GamePhase = 'ready' | 'playing' | 'review' | 'complete';

export interface HunterGene {
  geneId: string;
  discriminativeScore: number;
  /** Two classes, with an equal number of synthetic samples in each class. */
  expressionValues: [number[], number[]];
  isHighValue: boolean;
}

export interface GeneHunterLevel {
  levelId: number;
  title: string;
  classAName: string;
  classBName: string;
  description: string;
  genes: HunterGene[];
  topRankedGenes: string[];
  timeLimit: number;
  targetHits: number;
  source: 'synthetic';
}

/** A future API adapter can return the same level contract without changing the board. */
export interface GeneHunterLevelProvider {
  loadLevels(signal?: AbortSignal): Promise<readonly GeneHunterLevel[]>;
}

export interface GeneSelection { kind: HitKind; points: number; combo: number }
export interface HitFeedback extends GeneSelection { id: number; geneId: string }
export interface RoundResult {
  levelId: number;
  score: number;
  hits: number;
  stars: number;
  bestCombo: number;
  selections: Record<string, GeneSelection>;
}
export interface HunterState {
  phase: GamePhase;
  levelIndex: number;
  deadline: number | null;
  remainingMs: number;
  totalScore: number;
  roundScore: number;
  combo: number;
  bestCombo: number;
  selections: Record<string, GeneSelection>;
  feedback: HitFeedback | null;
  history: RoundResult[];
}
export interface HunterProgress {
  version: 1;
  bestScore: number;
  levelStars: Record<string, number>;
}

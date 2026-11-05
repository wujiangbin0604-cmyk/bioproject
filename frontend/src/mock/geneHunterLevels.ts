import type { GeneHunterLevel, GeneHunterLevelProvider, HunterGene } from '../games/gene-hunter/types';

// All values and rankings are authored teaching examples, not patient observations
// or a measured AUC. Reverse-direction signals are intentionally included.
function gene(geneId: string, score: number, seed: number, reverse = false): HunterGene {
  const separation = score >= .8 ? 1.45 : score >= .5 ? .65 : .08;
  const noise = score >= .8 ? .32 : score >= .5 ? .66 : 1.2;
  const group = (sign: number) => Array.from({ length: 8 }, (_, i) => {
    const jitter = (Math.sin((seed + 1) * (i + 2) * 2.37 + sign) + Math.cos(i * 1.8 + seed)) / 2;
    return Number(Math.max(-2, Math.min(2, sign * separation + jitter * noise)).toFixed(2));
  });
  return { geneId, discriminativeScore: score, expressionValues: [group(reverse ? -1 : 1), group(reverse ? 1 : -1)], isHighValue: score >= .8 };
}

const definitions = [
  { title: '初识表达差异', classAName: '模拟肿瘤组', classBName: '模拟正常组', timeLimit: 60,
    description: '从左右两组的色块差异出发，寻找组内相近、组间不同的基因。',
    names: ['EGFR', 'ACTB', 'MUC1', 'SLC2A1', 'VIM', 'KRT19', 'GAPDH', 'EPCAM', 'B2M', 'RPLP0', 'CDH1', 'TUBB'],
    scores: [.91, .12, .88, .86, .47, .94, .10, .89, .61, .28, .72, .35] },
  { title: '寻找双向信号', classAName: '模拟亚型 A', classBName: '模拟亚型 B', timeLimit: 55,
    description: '高表达和低表达都可能有价值。寻找方向相反、同样稳定的差异。',
    names: ['ESR1', 'RPS18', 'FOXA1', 'GATA3', 'MKI67', 'HPRT1', 'PGR', 'ERBB2', 'BCL2', 'LDHA', 'RPL13A', 'STAT3'],
    scores: [.95, .18, .89, .92, .67, .23, .87, .90, .58, .46, .13, .38] },
  { title: '穿过噪声', classAName: '模拟类别 A', classBName: '模拟类别 B', timeLimit: 50,
    description: '颜色很鲜明未必能区分类别。留意同一组内部的表达是否一致。',
    names: ['ALB', 'AFP', 'GPC3', 'ACTB', 'CYP3A4', 'KRT8', 'GAPDH', 'APOA1', 'VEGFA', 'RPLP0', 'MET', 'HIF1A'],
    scores: [.93, .87, .91, .16, .85, .63, .11, .90, .74, .32, .48, .41] },
  { title: '细微之处', classAName: '模拟类别 C', classBName: '模拟类别 D', timeLimit: 45,
    description: '同时观察两组：组间有差异、组内少波动的行更值得优先考虑。',
    names: ['NKX2-1', 'SFTPC', 'RPS18', 'KRT5', 'TP63', 'VIM', 'SOX2', 'B2M', 'CD44', 'KRT14', 'TUBB', 'JUN'],
    scores: [.94, .90, .22, .88, .92, .55, .71, .31, .43, .86, .19, .64] },
  { title: '关键特征猎手', classAName: '模拟类别 E', classBName: '模拟类别 F', timeLimit: 40,
    description: '综合运用你的观察：优先选择稳定的组间差异，并试着保持连击。',
    names: ['PAX8', 'CA9', 'ACTB', 'VHL', 'KRT7', 'GAPDH', 'SLC34A1', 'VEGFA', 'HPRT1', 'EGLN3', 'MET', 'B2M'],
    scores: [.93, .96, .15, .68, .87, .21, .90, .56, .33, .89, .49, .74] },
];

export const geneHunterLevels: readonly GeneHunterLevel[] = definitions.map((definition, index) => {
  const genes = definition.names.map((name, i) => gene(name, definition.scores[i], index * 17 + i, index > 0 && i % 3 === 0));
  return { levelId: index + 1, title: definition.title, classAName: definition.classAName, classBName: definition.classBName,
    description: definition.description, genes, timeLimit: definition.timeLimit, targetHits: 5, source: 'synthetic',
    topRankedGenes: [...genes].sort((a, b) => b.discriminativeScore - a.discriminativeScore).slice(0, 5).map(g => g.geneId) };
});

export const mockGeneHunterProvider: GeneHunterLevelProvider = {
  async loadLevels() { return geneHunterLevels; },
};

import test from 'node:test';
import assert from 'node:assert/strict';
import { geneHunterLevels as levels } from '../src/mock/geneHunterLevels.ts';
import { comboMultiplier, emptyProgress, hitKind, initialHunterState, mergeProgress, parseProgress, reduceHunterGame } from '../src/games/gene-hunter/gameEngine.ts';

const reduce = (state, action) => reduceHunterGame(state, action, levels);
const playing = () => reduce(initialHunterState(levels[0]), { type: 'start', now: 1000 });
const select = (state, geneId, now = 1001) => reduce(state, { type: 'select', geneId, now });
const highIds = level => level.genes.filter(g => g.isHighValue).map(g => g.geneId);

test('five coherent synthetic levels have 16 finite cells per gene and an accurate Top5', () => {
  assert.equal(levels.length, 5);
  for (const level of levels) {
    assert.equal(level.source, 'synthetic');
    assert.equal(new Set(level.genes.map(g => g.geneId)).size, level.genes.length);
    assert.equal(highIds(level).length, level.targetHits);
    assert.deepEqual(level.topRankedGenes, [...level.genes].sort((a,b) => b.discriminativeScore-a.discriminativeScore).slice(0,5).map(g => g.geneId));
    for (const gene of level.genes) {
      assert.equal(gene.isHighValue, gene.discriminativeScore >= .8);
      assert.deepEqual(gene.expressionValues.map(group => group.length), [8, 8]);
      assert.ok(gene.expressionValues.flat().every(v => Number.isFinite(v) && v >= -2 && v <= 2));
    }
  }
});
test('scoring boundaries and combo multipliers are exact', () => {
  assert.deepEqual([.49,.5,.799,.8,1].map(hitKind), ['low','medium','medium','high','high']);
  assert.deepEqual([0,1,2,3,4,5].map(comboMultiplier), [1,1,1.2,1.5,2,2]);
});
test('scores cannot change before starting and start cannot extend a running deadline', () => {
  const ready = initialHunterState(levels[0]);
  assert.equal(select(ready, 'KRT19'), ready);
  const state = playing();
  assert.equal(reduce(state, { type: 'start', now: 50000 }), state);
  assert.equal(state.deadline, 61000);
});
test('five high-value selections earn 800, 960, 1200, 1600, 1600', () => {
  let state = playing();
  const points = [];
  for (const id of highIds(levels[0])) { state = select(state, id); points.push(state.feedback.points); }
  assert.deepEqual(points, [800,960,1200,1600,1600]);
  assert.equal(state.totalScore, 6160); assert.equal(state.combo, 5); assert.equal(state.bestCombo, 5);
});
test('repeated or unknown genes never change points, feedback or combo', () => {
  const state = select(playing(), 'KRT19');
  for (let i = 0; i < 100; i++) assert.equal(select(state, 'KRT19'), state);
  assert.equal(select(state, 'not-a-gene'), state);
});
test('medium earns 300 and low earns zero; both interrupt high-value combos', () => {
  let state = select(select(playing(), 'KRT19'), 'EGFR');
  state = select(state, 'B2M');
  assert.equal(state.combo, 0); assert.equal(state.feedback.points, 300);
  state = select(state, 'EPCAM'); assert.equal(state.feedback.points, 800);
  const before = state.totalScore;
  state = select(state, 'ACTB');
  assert.equal(state.combo, 0); assert.equal(state.totalScore, before); assert.equal(state.bestCombo, 2);
});
test('click at or beyond the deadline ends the round without awarding points', () => {
  for (const now of [61000,61001,900000]) {
    const state = select(playing(), 'KRT19', now);
    assert.equal(state.phase, 'review'); assert.equal(state.totalScore, 0);
    assert.equal(state.history.length, 1); assert.equal(state.remainingMs, 0);
    assert.equal(select(state, 'EGFR', now), state);
  }
  assert.equal(select(playing(), 'KRT19', 60999).totalScore, 800);
});
test('absolute clock catches background throttling and round finalization is idempotent', () => {
  let state = reduce(playing(), { type: 'tick', now: 11000 });
  assert.equal(state.remainingMs, 50000);
  state = reduce(state, { type: 'tick', now: 95000 });
  assert.equal(state.phase, 'review'); assert.equal(state.history.length, 1);
  assert.equal(reduce(state, { type: 'tick', now: 96000 }), state);
  assert.equal(reduce(state, { type: 'finish', now: 96000 }), state);
});
test('zero, one, three and five hits receive zero, one, two and three stars', () => {
  for (const [count, stars] of [[0,0],[1,1],[3,2],[5,3]]) {
    let state = playing();
    for (const id of highIds(levels[0]).slice(0,count)) state = select(state,id);
    state = reduce(state, { type: 'finish', now: 2000 });
    assert.equal(state.history[0].stars, stars); assert.equal(state.history[0].hits, count);
  }
});
test('next resets round selections, combo, feedback and timer, preserving the run score', () => {
  const active = select(playing(), 'KRT19');
  assert.equal(reduce(active, { type: 'next' }), active);
  const state = reduce(reduce(active, { type: 'finish', now: 5000 }), { type: 'next' });
  assert.equal(state.phase,'ready'); assert.equal(state.levelIndex,1); assert.equal(state.totalScore,800);
  assert.equal(state.roundScore,0); assert.equal(state.combo,0); assert.equal(state.feedback,null);
  assert.deepEqual(state.selections,{}); assert.equal(state.remainingMs,55000);
});
test('complete five rounds, preserve best stars without farming and restart cleanly', () => {
  let state = initialHunterState(levels[0]);
  for (const level of levels) {
    state = reduce(state,{ type:'start', now:1000 });
    for (const id of highIds(level)) state = select(state,id);
    state = reduce(reduce(state,{ type:'finish', now:2000 }),{ type:'next' });
  }
  assert.equal(state.phase,'complete'); assert.equal(state.history.length,5); assert.equal(state.totalScore,30800);
  const progress = mergeProgress(emptyProgress,state);
  assert.equal(progress.bestScore,30800); assert.equal(Object.values(progress.levelStars).reduce((a,b)=>a+b,0),15);
  assert.deepEqual(mergeProgress(progress,state),progress);
  assert.deepEqual(reduce(state,{ type:'restart' }),initialHunterState(levels[0]));
  assert.equal(mergeProgress(emptyProgress, playing()).bestScore,0);
});
test('malformed or old local records are discarded safely', () => {
  for (const value of [null,[],{},'broken',{ version:0,bestScore:500 }]) assert.deepEqual(parseProgress(value),emptyProgress);
  assert.deepEqual(parseProgress({ version:1,bestScore:Infinity,levelStars:{ 1:3,2:10,3:-1,4:'3',5:2,6:3 } }),{ version:1,bestScore:0,levelStars:{ 1:3,5:2 } });
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { classColor, macroClassMetric, formatPercent, formatCount } from '../src/utils/dashboard.ts';

test('class colors stay consistent when data sources order labels differently', () => {
  for (const label of ['BRCA', 'KIRC', 'COAD', 'LUAD', 'PRAD']) assert.equal(classColor(label, ['PRAD', 'LUAD', 'COAD', 'KIRC', 'BRCA']), classColor(label, ['BRCA', 'KIRC', 'COAD', 'LUAD', 'PRAD']));
  assert.equal(classColor('normal', ['tumor', 'normal']), classColor('normal', ['normal', 'tumor']));
});

test('macro metrics average recorded classes, exclude report aggregates, and retain zero scores', () => {
  const result = { labels: ['A', 'B'], per_class: { A: { precision: 1, recall: .5 }, B: { precision: 0, recall: 1 }, 'weighted avg': { precision: .9, recall: .8 } } };
  assert.equal(macroClassMetric(result, 'precision'), .5);
  assert.equal(macroClassMetric(result, 'recall'), .75);
});
test('missing or nonfinite class scores are unavailable rather than fabricated as zero', () => {
  assert.equal(macroClassMetric(undefined, 'precision'), undefined);
  assert.equal(macroClassMetric({ labels: [], per_class: {} }, 'precision'), undefined);
  for (const value of [undefined, NaN, Infinity]) {
    assert.equal(macroClassMetric({ labels: ['A', 'B'], per_class: { A: { recall: 1 }, B: { recall: value } } }, 'recall'), undefined);
  }
});
test('dashboard distinguishes zero measurements from unavailable data', () => {
  assert.equal(formatPercent(0), '0.00%'); assert.equal(formatCount(0), '0');
  assert.equal(formatCount(null), '—'); assert.equal(formatPercent(NaN), '—');
  assert.equal(formatPercent(.98765), '98.77%');
});

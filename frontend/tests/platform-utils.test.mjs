import test from 'node:test';
import assert from 'node:assert/strict';
import { checkPredictionCsv } from '../src/utils/predictionCsv.ts';
import { allowedK, defaultConfig, validateExperiment } from '../src/utils/experiment.ts';
import { taskStages } from '../src/utils/taskStages.ts';

const dataset = { status: 'ready', features: 1200, class_counts: { A: 10, B: 8 }, quality: { constant_features: 300 } };
test('CSV supports BOM, CRLF, quoted names, exponent values and optional sample ID', () => {
  const checked = checkPredictionCsv('\uFEFFsample_id,"probe, A","probe""B"\r\n"S,1",-1.2e-3,2\r\n', ['probe"B', 'probe, A']);
  assert.equal(checked.error, undefined); assert.equal(checked.sampleId, 'S,1'); assert.equal(checked.featureCount, 2);
});
test('CSV rejects repeated columns without pandas-style silent renaming', () => assert.match(checkPredictionCsv('A,A\n1,2').error, /重复/));
test('CSV rejects multi-sample, broken quote and mismatched row lengths', () => {
  for (const text of ['A\n1\n2', 'A,B\n1', '"A\n1', '"A"b\n1']) assert.ok(checkPredictionCsv(text).error);
});
test('CSV rejects blanks, NaN, infinities, JS numeric literals and expression strings', () => {
  for (const bad of ['', 'NaN', 'Infinity', '0x20', '=1+2', 'hello']) assert.ok(checkPredictionCsv(`A,B\n2,${bad}`).error, bad);
});
test('CSV feature mismatch reports both missing and unexpected columns', () => assert.equal(checkPredictionCsv('B,C\n1,2', ['A','B']).error, '特征清单不匹配：缺少1列，多出1列'));
test('K respects effective feature count after constants are removed', () => assert.deepEqual(allowedK(dataset), [20,50,100,300,500]));
test('experiment validates ready data, class-size folds, discrete K and total work', () => {
  assert.deepEqual(validateExperiment(defaultConfig, dataset), {});
  assert.ok(validateExperiment(defaultConfig, { ...dataset, status: 'pending' }).dataset_id);
  assert.ok(validateExperiment({ ...defaultConfig, folds: 10 }, dataset).folds);
  assert.ok(validateExperiment({ ...defaultConfig, k: 21 }, dataset).k);
  assert.ok(validateExperiment({ ...defaultConfig, folds: 8, repeats: 5, algorithms: ['linear_svc','random_forest','rbf_svm'] }, dataset).repeats);
});
test('all-feature selection does not reject an unused K; null tree depth is accepted', () => assert.deepEqual(validateExperiment({ ...defaultConfig, selection: 'none', k: 21, max_depth: null }, dataset), {}));
test('CV stage mapping never claims internal fold steps completed mid-CV', () => {
  assert.deepEqual(taskStages({ status: 'running', completed_folds: 2, total_folds: 5 }), ['complete','active','active','active','pending']);
  assert.deepEqual(taskStages({ status: 'completed' }), Array(5).fill('complete'));
  assert.deepEqual(taskStages({ status: 'queued' }), Array(5).fill('pending'));
});
test('failure and cancellation retain stopped stages instead of success states', () => {
  for (const status of ['failed','cancelled','cancel_requested']) assert.deepEqual(taskStages({ status, completed_folds: 1 }), ['complete','stopped','stopped','stopped','pending']);
});

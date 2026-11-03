// Check actual release paths with a JavaScript port of Docker's ignore matcher.
// Test-only installation: npm install --prefix cloud_deployment/dist/dockerignore-check --no-save --no-package-lock @balena/dockerignore@1.0.2
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const ignore = require('./dist/dockerignore-check/node_modules/@balena/dockerignore');
const root = path.resolve(process.argv[2]);
const patterns = fs.readFileSync(path.join(root, '.dockerignore'), 'utf8');
const matcher = ignore().add(patterns);
assert.equal(matcher.ignores('datasets/registry.json'), false,
  'datasets/registry.json is excluded from the Docker COPY context');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'genescope2_manifest.json'), 'utf8'));
let required = 0, excluded = 0;
for (const relative of Object.keys(manifest.files)) {
  const first = relative.split('/')[0];
  const seed = ['experiment_runs', 'model_registry', 'development_data'].includes(first)
    || (first === 'datasets' && relative !== 'datasets/registry.json');
  assert.equal(matcher.ignores(relative), seed,
    seed ? `Private runtime data entered image context: ${relative}` : `Required code omitted: ${relative}`);
  seed ? excluded++ : required++;
}
console.log(JSON.stringify({ required_files_included: required, private_seed_files_excluded: excluded, registry_included: true }));

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { ESLint } from 'eslint';

const expectedDeferredRules = [
  'react-hooks/config',
  'react-hooks/error-boundaries',
  'react-hooks/gating',
  'react-hooks/globals',
  'react-hooks/immutability',
  'react-hooks/incompatible-library',
  'react-hooks/preserve-manual-memoization',
  'react-hooks/purity',
  'react-hooks/refs',
  'react-hooks/set-state-in-effect',
  'react-hooks/set-state-in-render',
  'react-hooks/static-components',
  'react-hooks/unsupported-syntax',
  'react-hooks/use-memo'
].sort();

function severity(rule: unknown) {
  return Array.isArray(rule) ? rule[0] : rule;
}

test('React hook correctness gates remain enabled', async () => {
  const eslint = new ESLint({ cwd: process.cwd() });
  const config = await eslint.calculateConfigForFile('app/page.tsx');

  assert.ok(config, 'ESLint must calculate a config for Web source files');
  assert.notEqual(severity(config.rules['react-hooks/rules-of-hooks']), 0);
  assert.notEqual(severity(config.rules['react-hooks/rules-of-hooks']), 'off');
  assert.notEqual(severity(config.rules['react-hooks/exhaustive-deps']), 0);
  assert.notEqual(severity(config.rules['react-hooks/exhaustive-deps']), 'off');
});

test('React Compiler deferrals stay explicitly bounded and owned', async () => {
  const source = await readFile(new URL('../eslint.config.mjs', import.meta.url), 'utf8');
  const deferredBlock = source.match(/const deferredReactCompilerRules = \{([\s\S]*?)\n\};/)?.[1];

  assert.ok(deferredBlock, 'the bounded React Compiler deferral must remain explicit');
  const deferredRules = [...deferredBlock.matchAll(/'([^']+)': 'off'/g)]
    .map((match) => match[1])
    .sort();
  assert.deepEqual(deferredRules, expectedDeferredRules);
  assert.match(source, /Owner: Web platform\./);
  assert.match(
    source,
    /Removal condition: complete the standalone behavior-preserving React Compiler\s+\* migration and clear every deferred-rule diagnostic\./
  );
});

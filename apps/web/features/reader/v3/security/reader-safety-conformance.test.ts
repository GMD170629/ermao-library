import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { generateWebReaderSafetyConformanceReport } from '../../../../scripts/generate-reader-safety-conformance';

const FIXTURE_ROOT = path.resolve(
  import.meta.dirname,
  '../../../../../../packages/reader-contracts/fixtures/reader-safety-v1'
);

async function loadJson(name: string): Promise<unknown> {
  return JSON.parse(await readFile(path.join(FIXTURE_ROOT, name), 'utf8')) as unknown;
}

function objectValue(value: unknown): object {
  assert.equal(typeof value, 'object');
  assert.notEqual(value, null);
  assert.ok(!Array.isArray(value));
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TypeError('Expected JSON object');
  }
  return value;
}

function expectedCases(value: unknown): ReadonlyMap<string, object> {
  const cases = Reflect.get(objectValue(value), 'cases');
  assert.ok(Array.isArray(cases));
  return new Map(cases.map((candidate: unknown) => {
    const candidateObject = objectValue(candidate);
    const caseId = Reflect.get(candidateObject, 'id');
    const expected = Reflect.get(candidateObject, 'expected');
    assert.equal(typeof caseId, 'string');
    return [caseId, objectValue(expected)] as const;
  }));
}

test('Web conformance report executes the production preflight facade', async () => {
  const suite = await loadJson('conformance-suite.json');
  const manifest = await loadJson('manifest.json');
  const expected = expectedCases(manifest);

  const report = await generateWebReaderSafetyConformanceReport(suite, manifest, 'web-test');

  assert.equal(report.consumer, 'WEB');
  assert.equal(report.results.length, 48);
  assert.deepEqual(report.omissions, []);
  for (const result of report.results) {
    const expectedResult = expected.get(result.caseId);
    assert.ok(expectedResult);
    assert.equal(result.action, Reflect.get(expectedResult, 'action'));
    assert.equal(result.errorCode, Reflect.get(expectedResult, 'errorCode'));
    assert.equal(result.terminalRuleId, Reflect.get(expectedResult, 'terminalRuleId'));
    assert.deepEqual(result.orderedRuleEvents, Reflect.get(expectedResult, 'orderedRuleEvents'));
    assert.equal(
      result.semanticProjectionSha256,
      Reflect.get(expectedResult, 'semanticProjectionSha256')
    );
  }
});

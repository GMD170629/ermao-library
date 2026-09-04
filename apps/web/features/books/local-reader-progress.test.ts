import assert from 'node:assert/strict';
import test from 'node:test';
import fixture from '../../../../packages/reader-contracts/fixtures/reader-v5/reflowable-empty-highlight.json';
import { latestLocalV5Progress, localV5ProgressPercent } from './local-reader-progress';
import { parseReaderV5PositionReport, type ReaderV5ProgressRecord } from '../../lib/reader/v5-wire';

function localProgress(capturedAtEpochMillis: number, displayPercent: number, resourceId = 'resource-1'): ReaderV5ProgressRecord {
  const position = parseReaderV5PositionReport({
    ...fixture.position,
    presentation: { ...fixture.position.presentation, displayPercent, totalProgression: displayPercent / 100 }
  });
  assert.ok(position);
  return {
    serverIdentity: 'https://reader.example',
    userId: 'user-1',
    clientId: 'web-client',
    bookId: 'book-1',
    resourceId,
    key: resourceId,
    schemaVersion: 5,
    mutationId: fixture.mutationId,
    revision: 0,
    capturedAtEpochMillis,
    position
  };
}

test('local v5 presentation overlays a stale server percentage without rollback', () => {
  const local = localProgress(20, 99);
  assert.equal(localV5ProgressPercent(25, local), 99);
  assert.equal(localV5ProgressPercent(25, null), 25);
});

test('book-level local resume picks the most recently captured readable resource', () => {
  const older = localProgress(10, 40, 'resource-old');
  const newer = localProgress(20, 99, 'resource-new');
  assert.equal(latestLocalV5Progress([older, newer])?.resourceId, 'resource-new');
  assert.equal(latestLocalV5Progress([older, newer])?.position.presentation.displayPercent, 99);
});

import assert from 'node:assert/strict';
import test from 'node:test';
import fixture from '../../../../../packages/reader-contracts/fixtures/reader-v5/reflowable-empty-highlight.json';
import { parseReaderV5PositionReport, type ReaderV5PendingMutation, type ReaderV5ProgressIdentity, type ReaderV5ProgressRecord } from '../../../lib/reader/v5-wire';
import { latestLocalV5Progress, localV5ProgressPercent } from '../local-reader-progress';
import { loadBookLocalProgress } from './load-local-reader-progress';

const identity = { serverIdentity: 'https://reader.example', userId: 'user-1', bookId: 'book-1' };
const position = parseReaderV5PositionReport(fixture.position);
assert.ok(position);
const exact: ReaderV5ProgressRecord = {
  ...identity, clientId: 'web-client', resourceId: 'old-resource', key: 'local-exact',
  schemaVersion: 5, mutationId: fixture.mutationId, capturedAtEpochMillis: 20,
  revision: 7, position
};

test('acknowledged local position cannot replace a newer server detail or resume resource', async () => {
  const storage = {
    async getClientId() { return exact.clientId; },
    async getV5Progress() { return exact; },
    async getV5PendingProgressForIdentity() { return null; }
  };
  const records = await loadBookLocalProgress(storage, identity, ['old-resource']);
  const local = latestLocalV5Progress(records);
  assert.equal(localV5ProgressPercent(50, local), 50);
  assert.equal(local, null);
  assert.deepEqual(records, []);
});

test('unconfirmed report preserves its complete presentation and identity over server detail', async () => {
  const pending: ReaderV5PendingMutation = { ...exact, key: 'pending' };
  const storage = {
    async getClientId() { return exact.clientId; },
    async getV5Progress() { return exact; },
    async getV5PendingProgressForIdentity(request: ReaderV5ProgressIdentity) {
      assert.deepEqual(request, { ...identity, clientId: exact.clientId, resourceId: exact.resourceId });
      return pending;
    }
  };
  const records = await loadBookLocalProgress(storage, identity, [exact.resourceId]);
  assert.equal(records.length, 1);
  assert.equal(records[0]?.resourceId, pending.resourceId);
  assert.equal(localV5ProgressPercent(50, latestLocalV5Progress(records)), pending.position.presentation.displayPercent);
  assert.deepEqual(records[0]?.position, position);
});

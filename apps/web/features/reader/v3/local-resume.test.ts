import assert from 'node:assert/strict';
import test from 'node:test';
import exactRequest from '../../../../../packages/reader-contracts/fixtures/exact-reflowable-request.json';
import { parsePublicationLocation } from '@shuku/reader-core';
import { type ExactProgressRecord, type PendingProgressMutation, type ReaderProgressSnapshot, v4LocationToDomain } from '../../../lib/reader';
import { decidePendingVsServer, resolveStartupResume } from './local-resume';

const locator = parsePublicationLocation(exactRequest.locator);
if (!locator) throw new Error('invalid exact fixture');

const exact: ExactProgressRecord = {
  key: 'exact', schemaVersion: 1, serverIdentity: 'server', userId: 'user', clientId: 'web-client',
  workId: 'work', volumeId: 'volume', locator,
  displayPercent: 12, revision: 4, capturedAtEpochMillis: 100
};
const pending: PendingProgressMutation = {
  key: 'pending', schemaVersion: 1, serverIdentity: 'server', userId: 'user', clientId: 'web-client',
  workId: 'work', volumeId: 'volume', mutationId: '11111111-1111-4111-8111-111111111111',
  baseRevision: 4, capturedAtEpochMillis: 100, locator, displayPercent: 12
};
const server = (revision: number): ReaderProgressSnapshot => ({
  schemaVersion: 4, clientId: 'ios-client', revision, locator, displayPercent: 12, receivedAtEpochMillis: 110
});

test('online startup ignores confirmed local history and uses the fresh server snapshot', () => {
  const decision = resolveStartupResume({
    localExact: exact, serverSnapshot: server(8), context: { readerKind: 'reflowable', sourceFormat: 'epub' },
    serverLocation: v4LocationToDomain(locator, 'volume', 'epub'), serverPercent: 12, hasDirectTarget: false
  });
  assert.equal(decision.source, 'server');
  assert.equal(decision.localExact, null);
});

test('a pending mutation at the current revision resumes locally without a choice', () => {
  assert.equal(decidePendingVsServer({ localExact: exact, pending, serverSnapshot: server(4) }).kind, 'local-pending');
});

test('a newer server revision requires a startup choice', () => {
  assert.equal(decidePendingVsServer({ localExact: exact, pending, serverSnapshot: server(5) }).kind, 'requires-choice');
});

test('a publication fingerprint change does not invalidate pending progress for the same work and volume', () => {
  const changedPublication = { ...pending, locator: { ...locator, publication: { ...locator.publication, normalization: 'different' } } };
  const decision = decidePendingVsServer({ localExact: exact, pending: changedPublication, serverSnapshot: server(5) });
  assert.equal(decision.kind, 'requires-choice');
});

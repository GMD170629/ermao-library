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
  bookId: 'book', resourceId: 'resource', locator,
  displayPercent: 12, revision: 4, capturedAtEpochMillis: 100
};
const pending: PendingProgressMutation = {
  key: 'pending', schemaVersion: 1, serverIdentity: 'server', userId: 'user', clientId: 'web-client',
  bookId: 'book', resourceId: 'resource', mutationId: '11111111-1111-4111-8111-111111111111',
  baseRevision: 4, capturedAtEpochMillis: 100, locator, displayPercent: 12
};
const server = (revision: number, capturedAtEpochMillis = 110): ReaderProgressSnapshot => ({
  schemaVersion: 4, clientId: 'ios-client', revision, locator, displayPercent: 12,
  receivedAtEpochMillis: 110, capturedAtEpochMillis
});
const decide = (input: Parameters<typeof decidePendingVsServer>[0]) => decidePendingVsServer(input);
const identity = { bookId: 'book', resourceId: 'resource' } as const;

test('online startup ignores confirmed local history and uses the fresh server snapshot', () => {
  const decision = resolveStartupResume({
    localExact: exact, serverSnapshot: server(8), context: { readerKind: 'reflowable', sourceFormat: 'epub' },
    serverLocation: v4LocationToDomain(locator, 'resource', 'epub'), serverPercent: 12, hasDirectTarget: false,
    bookId: 'book', resourceId: 'resource'
  });
  assert.equal(decision.source, 'server');
  assert.equal(decision.localExact, null);
});

test('online startup restores a newer valid local exact position without blocking', () => {
  const newerLocal = { ...exact, capturedAtEpochMillis: 200 };
  const decision = resolveStartupResume({
    localExact: newerLocal, serverSnapshot: server(8, 150), context: { readerKind: 'reflowable', sourceFormat: 'epub' },
    serverLocation: v4LocationToDomain(locator, 'resource', 'epub'), serverPercent: 12, hasDirectTarget: false,
    bookId: 'book', resourceId: 'resource'
  });
  assert.equal(decision.source, 'local-exact');
  assert.equal(decision.localExact?.capturedAtEpochMillis, 200);
});

test('server wins an equal capture timestamp', () => {
  const decision = resolveStartupResume({
    localExact: exact, serverSnapshot: server(8, 100), context: { readerKind: 'reflowable', sourceFormat: 'epub' },
    serverLocation: v4LocationToDomain(locator, 'resource', 'epub'), serverPercent: 12, hasDirectTarget: false,
    bookId: 'book', resourceId: 'resource'
  });
  assert.equal(decision.source, 'server');
});

test('an explicit target wins over local and server progress', () => {
  const decision = resolveStartupResume({
    localExact: { ...exact, capturedAtEpochMillis: 200 }, serverSnapshot: server(8, 150),
    context: { readerKind: 'reflowable', sourceFormat: 'epub' },
    serverLocation: v4LocationToDomain(locator, 'resource', 'epub'), serverPercent: 12, hasDirectTarget: true,
    bookId: 'book', resourceId: 'resource'
  });
  assert.equal(decision.source, 'direct-target');
});

test('a pending mutation at the current revision resumes locally without a choice', () => {
  const decision = decide({ localExact: exact, pending, serverSnapshot: server(4), ...identity });
  assert.equal(decision.kind, 'local-pending');
  if (decision.kind === 'local-pending') assert.equal(decision.rebaseRevision, null);
});

test('a newer remote position deterministically retires an older pending mutation', () => {
  const decision = decide({ localExact: exact, pending, serverSnapshot: server(5, 110), ...identity });
  assert.equal(decision.kind === 'server' ? decision.discardPendingMutationId : null, pending.mutationId);
});

test('a newer local pending position rebases onto the fresh remote revision', () => {
  const newerLocal = { ...exact, capturedAtEpochMillis: 200 };
  const newerPending = { ...pending, capturedAtEpochMillis: 200 };
  const decision = decide({ localExact: newerLocal, pending: newerPending, serverSnapshot: server(5, 150), ...identity });
  assert.equal(decision.kind, 'local-pending');
  if (decision.kind === 'local-pending') assert.equal(decision.rebaseRevision, 5);
});

test('pending progress remains scoped to the same book and resource', () => {
  const decision = decide({
    localExact: { ...exact, bookId: 'other-book' },
    pending: { ...pending, locator: { ...locator } },
    serverSnapshot: server(5),
    ...identity
  });
  assert.equal(decision.kind === 'server' ? decision.discardPendingMutationId : null, pending.mutationId);
});

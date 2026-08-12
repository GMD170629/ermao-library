import assert from 'node:assert/strict';
import test from 'node:test';
import { exactProgressKey, type ExactProgressRecord, type ReaderProgressSnapshot } from '../../../lib/reader';
import { resolveStartupResume } from './local-resume';

function exact(updatedAtEpochMillis: number, pageNumber = 7): ExactProgressRecord {
  const identity = {
    serverIdentity: 'https://library.example',
    userId: 'user-1',
    clientId: 'web-1',
    volumeId: 'volume-1',
    localContentFingerprint: 'volume-version-1'
  };
  return {
    ...identity,
    key: exactProgressKey(identity),
    schemaVersion: 1,
    workId: 'work-1',
    location: { kind: 'pdf', pageNumber },
    percent: 35,
    updatedAtEpochMillis
  };
}

function server(updatedAtEpochMillis: number): ReaderProgressSnapshot {
  return {
    schemaVersion: 4,
    clientId: 'ios-1',
    updatedAtEpochMillis,
    percent: 60,
    location: { kind: 'pdf', pageNumber: 12 },
    contentFingerprint: 'volume-version-1'
  };
}

test('explicit navigation remains stronger than local or server resume', () => {
  const decision = resolveStartupResume({
    localExact: exact(200),
    serverSnapshot: server(300),
    context: { readerKind: 'pdf' },
    serverLocation: { kind: 'pdf', pageNumber: 3 },
    serverPercent: 10,
    hasDirectTarget: true
  });
  assert.equal(decision.source, 'direct-target');
  assert.deepEqual(decision.location, { kind: 'pdf', pageNumber: 3 });
});

test('local exact position wins when its client timestamp is newer or tied', () => {
  for (const localTime of [301, 300]) {
    const decision = resolveStartupResume({
      localExact: exact(localTime),
      serverSnapshot: server(300),
      context: { readerKind: 'pdf' },
      serverLocation: { kind: 'pdf', pageNumber: 12 },
      serverPercent: 60,
      hasDirectTarget: false
    });
    assert.equal(decision.source, 'local-exact');
    assert.deepEqual(decision.location, { kind: 'pdf', pageNumber: 7 });
    assert.equal(decision.percent, 35);
  }
});

test('newer server snapshot uses the already-decoded remote fallback location', () => {
  const decision = resolveStartupResume({
    localExact: exact(299),
    serverSnapshot: server(300),
    context: { readerKind: 'pdf' },
    serverLocation: { kind: 'pdf', pageNumber: 12 },
    serverPercent: 60,
    hasDirectTarget: false
  });
  assert.equal(decision.source, 'server');
  assert.deepEqual(decision.location, { kind: 'pdf', pageNumber: 12 });
  assert.equal(decision.percent, 60);
});

test('a local exact position is ignored when it belongs to another reader kind', () => {
  const decision = resolveStartupResume({
    localExact: exact(400),
    serverSnapshot: server(300),
    context: { readerKind: 'comic' },
    serverLocation: { kind: 'comic', volumeId: 'volume-1', pageIndex: 4 },
    serverPercent: 20,
    hasDirectTarget: false
  });
  assert.equal(decision.source, 'server');
});

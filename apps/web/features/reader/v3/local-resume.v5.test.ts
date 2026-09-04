import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveV5StartupResume } from './local-resume';

const position = {
  locator: { href: 'chapter.xhtml' },
  presentation: {
    displayPercent: 42,
    totalProgression: 0.42,
    currentHref: 'chapter.xhtml',
    chapter: { href: 'chapter.xhtml', title: 'Chapter', index: 2 },
    page: null,
    playback: null
  }
} as const;

test('v5 startup priority is explicit target, pending, server, then beginning', () => {
  const pending = {
    serverIdentity: 'same-origin', userId: 'user', clientId: 'web', bookId: 'book', resourceId: 'resource',
    key: 'pending', schemaVersion: 5 as const, mutationId: '11111111-1111-4111-8111-111111111111',
    capturedAtEpochMillis: 1, position
  };
  const serverSnapshot = {
    schemaVersion: 5 as const, revision: 1, clientId: 'ios', mutationId: '22222222-2222-4222-8222-222222222222',
    capturedAtEpochMillis: 1, receivedAtEpochMillis: 2, position
  };
  assert.equal(resolveV5StartupResume({ hasDirectTarget: true, directPosition: null, pending, serverSnapshot }).source, 'direct-target');
  assert.equal(resolveV5StartupResume({ directPosition: null, pending, serverSnapshot }).source, 'local-pending');
  assert.equal(resolveV5StartupResume({ directPosition: null, pending: null, serverSnapshot }).source, 'server');
  assert.equal(resolveV5StartupResume({ directPosition: null, pending: null, serverSnapshot: null }).source, 'start');
});

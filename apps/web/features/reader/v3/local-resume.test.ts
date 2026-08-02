import assert from 'node:assert/strict';
import test from 'node:test';
import type { ProgressMutation } from '../../../lib/reader';
import { newestLocalResume, resolveStartupResume } from './local-resume';

function mutation(overrides: Partial<ProgressMutation> = {}): ProgressMutation {
  return {
    schemaVersion: 3,
    mutationId: 'mutation-1',
    clientId: 'client-1',
    clientSequence: 1,
    slotKey: 'slot',
    userId: 'user-1',
    workId: 'work-1',
    volumeId: 'volume-1',
    contentFingerprint: 'sha256:current',
    location: { kind: 'reflowable', format: 'epub', cfi: 'epubcfi(/6/2)' },
    percent: 12,
    createdAt: 100,
    updatedAt: 100,
    retryCount: 0,
    nextAttemptAt: 100,
    ...overrides
  };
}

const context = {
  userId: 'user-1',
  volumeId: 'volume-1',
  contentFingerprint: 'sha256:current',
  readerKind: 'reflowable' as const,
  sourceFormat: 'epub' as const
};

test('restores the newest exact local CFI ahead of an older server snapshot', () => {
  const latest = mutation({
    mutationId: 'mutation-2',
    clientSequence: 2,
    location: { kind: 'reflowable', format: 'epub', cfi: 'epubcfi(/6/8)' },
    percent: 38,
    updatedAt: 200
  });
  assert.equal(newestLocalResume([latest, mutation()], context), latest);
});

test('upgrades a pending legacy EPUB anchor before foliate restores it', () => {
  const legacy = mutation({
    location: { kind: 'epub', cfi: 'epubcfi(/6/12)', href: 'legacy.xhtml', progression: 0.7 }
  });
  assert.deepEqual(newestLocalResume([legacy], context)?.location, {
    kind: 'reflowable',
    format: 'epub',
    cfi: 'epubcfi(/6/12)',
    href: 'legacy.xhtml',
    progression: 0.7
  });
});

test('never crosses content, volume, owner, or reader boundaries', () => {
  const candidates = [
    mutation({ contentFingerprint: 'sha256:old' }),
    mutation({ volumeId: 'volume-2' }),
    mutation({ userId: 'user-2' }),
    mutation({ volumeId: 'volume-3' }),
    mutation({ location: { kind: 'pdf', pageNumber: 7 } }),
    mutation({
      location: {
        kind: 'audio',
        volumeId: 'volume-1',
        fileId: 'track-1',
        chapterId: null,
        positionMs: 42_000
      }
    })
  ];
  assert.equal(newestLocalResume(candidates, context), null);
});

test('startup reconciliation prefers the newest pending CFI over an older server snapshot', () => {
  const latest = mutation({
    mutationId: 'mutation-3',
    clientSequence: 3,
    location: {
      kind: 'reflowable',
      format: 'epub',
      cfi: 'epubcfi(/6/8!/4/2/6)',
      href: 'chapter-2.xhtml',
      progression: 0.42
    },
    percent: 42,
    updatedAt: 300
  });
  const decision = resolveStartupResume({
    mutations: [mutation(), latest],
    context,
    initialLocation: { kind: 'reflowable', format: 'epub', cfi: 'epubcfi(/6/2!/4/2/2)', href: 'chapter-1.xhtml', progression: 0.04 },
    progressPercent: 4,
    hasDirectTarget: false
  });

  assert.equal(decision.source, 'local-pending');
  assert.equal(decision.localMutation, latest);
  assert.equal(decision.location, latest.location);
  assert.equal(decision.percent, 42);
});

test('a validated explicit href wins over a pending local CFI', () => {
  const directLocation = { kind: 'reflowable' as const, format: 'epub' as const, href: 'chapter-1.xhtml#opening' };
  const decision = resolveStartupResume({
    mutations: [mutation({
      clientSequence: 9,
      location: { kind: 'reflowable', format: 'epub', cfi: 'epubcfi(/6/8!/4/2/6)', href: 'chapter-2.xhtml' },
      percent: 65
    })],
    context,
    initialLocation: directLocation,
    progressPercent: 12,
    hasDirectTarget: true
  });

  assert.deepEqual(decision, {
    location: directLocation,
    percent: 12,
    source: 'direct-target',
    localMutation: null
  });
});

test('startup reconciliation preserves the server snapshot without an exact pending mutation', () => {
  const serverLocation = { kind: 'reflowable' as const, format: 'epub' as const, cfi: 'epubcfi(/6/4!/4/2/2)', progression: 0.23 };
  const decision = resolveStartupResume({
    mutations: [mutation({ contentFingerprint: 'sha256:another-rendition', clientSequence: 10 })],
    context,
    initialLocation: serverLocation,
    progressPercent: 23,
    hasDirectTarget: false
  });

  assert.deepEqual(decision, {
    location: serverLocation,
    percent: 23,
    source: 'server',
    localMutation: null
  });
});

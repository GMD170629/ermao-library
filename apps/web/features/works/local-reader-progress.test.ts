import assert from 'node:assert/strict';
import test from 'node:test';
import type { ProgressMutation } from '../../lib/reader/model';
import { latestScopedProgress, localProgressProjection } from './local-reader-progress';

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
    location: { kind: 'pdf', pageNumber: 2 },
    percent: 20,
    createdAt: 1,
    updatedAt: 1,
    retryCount: 0,
    nextAttemptAt: 1,
    ...overrides
  };
}

test('latestScopedProgress isolates user, volume, and content fingerprint', () => {
  const latest = mutation({ mutationId: 'latest', clientSequence: 3 });
  const result = latestScopedProgress([
    mutation({ mutationId: 'other-user', userId: 'user-2', clientSequence: 9 }),
    mutation({ mutationId: 'stale-content', contentFingerprint: 'sha256:old', clientSequence: 8 }),
    mutation({ mutationId: 'older', clientSequence: 2 }),
    latest
  ], {
    userId: 'user-1',
    workId: 'work-1',
    volumeId: 'volume-1',
    contentFingerprint: 'sha256:current'
  });
  assert.equal(result?.mutationId, 'latest');
});

test('localProgressProjection exposes foliate TOC, Loc, and remaining time', () => {
  const projected = localProgressProjection(mutation({
    percent: 42.5,
    location: {
      kind: 'reflowable',
      format: 'epub',
      cfi: 'epubcfi(/6/4)',
      progression: 0.425,
      foliate: {
        toc: { index: 4, title: 'Chapter 5', href: 'chapter-5.xhtml' },
        location: { current: 41, next: 43, total: 100 },
        remainingSeconds: { section: 180, total: 720 }
      }
    }
  }));
  assert.deepEqual(projected, {
    percent: 42.5,
    currentHref: 'chapter-5.xhtml',
    currentChapterIndex: 4,
    currentChapterTitle: 'Chapter 5',
    locationCurrent: 41,
    locationNext: 43,
    locationTotal: 100,
    remainingSectionSeconds: 180,
    remainingTotalSeconds: 720
  });
});

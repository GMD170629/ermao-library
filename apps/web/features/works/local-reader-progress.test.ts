import assert from 'node:assert/strict';
import test from 'node:test';
import { exactProgressKey, type ExactProgressRecord } from '../../lib/reader/model';
import { latestScopedProgress, localProgressProjection } from './local-reader-progress';

function mutation(overrides: Partial<ExactProgressRecord> = {}): ExactProgressRecord {
  const identity = {
    serverIdentity: 'https://library.example',
    userId: 'user-1',
    clientId: 'client-1',
    volumeId: 'volume-1',
    localContentFingerprint: 'sha256:current'
  };
  return {
    ...identity,
    key: exactProgressKey(identity),
    schemaVersion: 1,
    workId: 'work-1',
    location: { kind: 'pdf', pageNumber: 2 },
    percent: 20,
    updatedAtEpochMillis: 1,
    ...overrides
  };
}

test('latestScopedProgress isolates user, volume, and content fingerprint', () => {
  const latest = mutation({ updatedAtEpochMillis: 3 });
  const result = latestScopedProgress([
    mutation({ userId: 'user-2', updatedAtEpochMillis: 9 }),
    mutation({ localContentFingerprint: 'sha256:old', updatedAtEpochMillis: 8 }),
    mutation({ updatedAtEpochMillis: 2 }),
    latest
  ], {
    userId: 'user-1',
    workId: 'work-1',
    volumeId: 'volume-1',
    contentFingerprint: 'sha256:current'
  });
  assert.equal(result?.updatedAtEpochMillis, 3);
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

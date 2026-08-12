import assert from 'node:assert/strict';
import test from 'node:test';
import type { AudioProgressLocation } from '../../lib/reader/model';
import { MemoryReaderStorage } from '../../lib/reader/memory-storage';
import { toV4WireLocation } from '../../lib/reader/progress-wire';
import { ReaderProgressSyncCoordinator } from '../../lib/reader/sync-coordinator';

test('serializes standard audio progress on the Reader v4 location contract', () => {
  const location: AudioProgressLocation = {
    kind: 'audio',
    volumeId: 'volume-1',
    fileId: 'file-1',
    chapterId: 'chapter-2',
    positionMs: 42_500
  };
  assert.deepEqual(toV4WireLocation(location), {
    kind: 'audio',
    fileId: 'file-1',
    chapterId: 'chapter-2',
    positionMs: 42_500
  });
});

test('serializes Foliate engine data while keeping resource progression semantic', () => {
  assert.deepEqual(toV4WireLocation({
    kind: 'reflowable',
    format: 'azw3',
    cfi: 'epubcfi(/6/8)',
    href: 'text/chapter.xhtml',
    progression: 0.6,
    foliate: { continuous: { sectionFraction: 0.25 } }
  }), {
    kind: 'reflow',
    resourceKey: 'text/chapter.xhtml',
    progression: 0.25,
    engineLocator: {
      engine: 'foliate',
      platform: 'web',
      version: 'foliate-web-v1',
      payload: {
        cfi: 'epubcfi(/6/8)',
        href: 'text/chapter.xhtml',
        fraction: 0.6,
        foliate: { continuous: { sectionFraction: 0.25 } }
      }
    }
  });
});

test('audio uses the same exact-first, one-shot v4 uploader', async () => {
  const storage = new MemoryReaderStorage();
  const location: AudioProgressLocation = {
    kind: 'audio',
    volumeId: 'volume-1',
    fileId: 'track-3',
    chapterId: null,
    positionMs: 75_250
  };
  const sent: unknown[] = [];
  const coordinator = new ReaderProgressSyncCoordinator(storage, async (upload) => {
    sent.push(upload.snapshot.location);
    return upload.snapshot;
  }, { debounceMs: 5 });
  coordinator.activateUser('user-1');
  await coordinator.enqueue({
    serverIdentity: 'https://library.example',
    userId: 'user-1',
    workId: 'work-1',
    volumeId: 'volume-1',
    localContentFingerprint: 'sha256:local-volume-1',
    contentFingerprint: 'volume-version-1',
    location,
    percent: 25
  });
  await coordinator.flushNow();
  assert.deepEqual(sent, [{ kind: 'audio', fileId: 'track-3', chapterId: null, positionMs: 75_250 }]);
});

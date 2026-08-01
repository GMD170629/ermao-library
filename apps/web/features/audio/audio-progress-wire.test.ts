import assert from 'node:assert/strict';
import test from 'node:test';
import type { AudioProgressLocation } from '../../lib/reader-v2/model';
import { MemoryReaderV2Storage } from '../../lib/reader-v2/memory-storage';
import { toWireLocation } from '../../lib/reader-v2/runtime';
import { ReaderProgressSyncCoordinator } from '../../lib/reader-v2/sync-coordinator';

test('serializes audio progress into the Reader V2 wire location', () => {
  const location: AudioProgressLocation = {
    kind: 'audio',
    volumeId: null,
    fileId: 'file-1',
    chapterId: 'chapter-2',
    positionMs: 42_500
  };
  assert.deepEqual(toWireLocation(location), {
    type: 'audio',
    volumeId: null,
    fileId: 'file-1',
    chapterId: 'chapter-2',
    positionMs: 42_500
  });
});

test('keeps visual reader locations on the existing Reader V2 wire contract', () => {
  assert.deepEqual(toWireLocation({ kind: 'epub', cfi: 'epubcfi(/6/2)', href: 'chapter.xhtml' }), {
    type: 'epub',
    cfi: 'epubcfi(/6/2)',
    href: 'chapter.xhtml',
    spineIndex: undefined,
    progression: undefined
  });
  assert.deepEqual(toWireLocation({ kind: 'comic', volumeId: 'volume-1', pageIndex: 8 }), {
    type: 'comic',
    volumeId: 'volume-1',
    pageIndex: 8
  });
  assert.deepEqual(toWireLocation({ kind: 'pdf', pageNumber: 17 }), {
    type: 'pdf',
    pageNumber: 17
  });
});

test('serializes foliate positions with their original source format', () => {
  assert.deepEqual(toWireLocation({ kind: 'reflowable', format: 'azw3', cfi: 'epubcfi(/6/8)', progression: 0.6 }), {
    type: 'reflowable',
    format: 'azw3',
    cfi: 'epubcfi(/6/8)',
    href: undefined,
    progression: 0.6
  });
});

test('durably queues audio through the shared Reader V2 progress coordinator', async () => {
  const storage = new MemoryReaderV2Storage();
  const location: AudioProgressLocation = {
    kind: 'audio',
    volumeId: 'volume-1',
    fileId: 'track-3',
    chapterId: null,
    positionMs: 75_250
  };
  const sent: AudioProgressLocation[] = [];
  const coordinator = new ReaderProgressSyncCoordinator(storage, async (mutation) => {
    if (mutation.location.kind === 'audio') sent.push(mutation.location);
    return { outcome: 'accepted' };
  }, { debounceMs: 60_000 });

  await coordinator.enqueue({
    userId: 'user-1',
    workId: 'work-1',
    editionId: 'audio-edition-1',
    volumeId: 'volume-1',
    contentFingerprint: 'sha256:audio',
    location,
    percent: 25
  });
  await coordinator.flushNow();
  coordinator.stop();

  assert.deepEqual(sent, [location]);
  assert.deepEqual(await storage.listProgress(), []);
});

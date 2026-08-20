import test from 'node:test';
import assert from 'node:assert/strict';
import { IMPLICIT_VERSION_SOURCE_KEY, type VersionResource, type VolumeResource, type WorkView } from '../../types/work';
import {
  selectedVolumeForWork,
  shouldShowVersionHeadings,
  versionDisplayTitle,
  workDetailHref
} from './work-detail';

function volume(id: string, versionId: string, sortOrder: number, progress = 0): VolumeResource {
  return {
    id,
    versionId,
    title: id,
    volumeIndex: null,
    sortOrder,
    format: 'EPUB',
    readerType: 'reflowable',
    classification: { source: 'LEGACY', reason: 'LEGACY', suggestedMediaKind: null },
    publisher: null,
    publishedAt: null,
    language: null,
    isbn: null,
    identifier: null,
    narrator: null,
    abridged: null,
    importStatus: 'READY',
    importError: null,
    coverUrl: '',
    sizeBytes: 0,
    pageCount: null,
    chapterCount: null,
    durationMs: null,
    trackCount: null,
    progress,
    lastReadAt: null,
    hidden: false,
    readable: true,
    kindleSendAvailable: true,
    files: []
  };
}

function version(partial: Partial<VersionResource> & Pick<VersionResource, 'id' | 'volumes'>): VersionResource {
  return {
    sourceKey: IMPLICIT_VERSION_SOURCE_KEY,
    sourceName: null,
    completed: false,
    volumeCount: partial.volumes.length,
    sizeBytes: 0,
    ...partial
  };
}

function work(versions: VersionResource[], continueVolumeId: string | null = null): WorkView {
  return {
    id: 'work-1',
    title: '书',
    author: '作者',
    description: '',
    seriesName: null,
    seriesIndex: null,
    tags: [],
    publicationStatus: 'UNKNOWN',
    trackingStatus: 'NOT_TRACKING',
    ignored: false,
    organized: true,
    metadataQuality: 100,
    addedAt: '',
    updatedAt: '',
    coverUrl: '',
    coverStatus: '',
    gradient: '',
    continueVolumeId,
    completed: false,
    versions
  };
}

test('deep links use volumeId without detailTab', () => {
  assert.equal(workDetailHref('work/下一部', 'volume/1'), '/works/work%2F%E4%B8%8B%E4%B8%80%E9%83%A8?volumeId=volume%2F1');
  assert.equal(
    workDetailHref('work-1', null, '/library?status=READING&sort=title'),
    '/works/work-1?returnTo=%2Flibrary%3Fstatus%3DREADING%26sort%3Dtitle'
  );
  assert.equal(workDetailHref('work-1').includes('detailTab'), false);
});

test('single implicit version hides the version heading', () => {
  const value = work([version({ id: 'implicit', volumes: [volume('v1', 'implicit', 0)] })]);
  assert.equal(shouldShowVersionHeadings(value), false);
  assert.equal(versionDisplayTitle(value.versions[0]!), null);
});

test('multiple versions partition and prefer sourceName then sourceKey', () => {
  const implicit = version({ id: 'implicit', volumes: [volume('a', 'implicit', 0)] });
  const named = version({
    id: 'named',
    sourceKey: 'calibre',
    sourceName: 'Calibre 导入',
    volumes: [volume('b', 'named', 0)]
  });
  const keyOnly = version({
    id: 'key-only',
    sourceKey: 'vendor',
    sourceName: null,
    volumes: [volume('c', 'key-only', 0)]
  });
  const value = work([implicit, named, keyOnly]);
  assert.equal(shouldShowVersionHeadings(value), true);
  assert.equal(versionDisplayTitle(implicit), null);
  assert.equal(versionDisplayTitle(named), 'Calibre 导入');
  assert.equal(versionDisplayTitle(keyOnly), 'vendor');
});

test('volume selection prefers URL, continue, first unfinished, then first volume', () => {
  const first = volume('first', 'implicit', 0, 100);
  const continueVolume = volume('continue', 'named', 1, 20);
  const unfinished = volume('unfinished', 'named', 2, 0);
  const value = work(
    [
      version({ id: 'implicit', volumes: [first] }),
      version({ id: 'named', sourceKey: 'named', sourceName: 'Named', volumes: [continueVolume, unfinished] })
    ],
    'continue'
  );
  assert.equal(selectedVolumeForWork(value, 'unfinished')?.id, 'unfinished');
  assert.equal(selectedVolumeForWork(value)?.id, 'continue');
  assert.equal(selectedVolumeForWork({ ...value, continueVolumeId: null })?.id, 'continue');
});

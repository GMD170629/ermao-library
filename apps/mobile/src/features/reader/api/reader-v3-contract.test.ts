import assert from 'node:assert/strict';
import test from 'node:test';

import type { ReaderBootstrapResponse } from '../../../../generated/reader-v3';
import {
  createReaderProgressPut,
  mapReaderBootstrapToSource,
  mapReaderLocationFromWire,
} from './reader-v3-mapper';
import {
  decodeReaderBootstrapResponse,
  decodeReaderErrorBody,
  decodeReaderErrorResponse,
  decodeReaderLocationWire,
} from './reader-v3-wire';

function bootstrapResponse(): ReaderBootstrapResponse {
  return {
    ok: true,
    data: {
      schemaVersion: 3,
      userId: 'user-1',
      readerType: 'reflowable',
      sourceFormat: 'epub',
      contentFingerprint: 'sha256:book-content',
      book: {
        id: 'work-1',
        title: '银河边缘',
        author: '作者甲',
        coverUrl: '/api/works/work-1/cover',
      },
      mediaVersion: {
        id: 'media-1',
        workId: 'work-1',
        mediaKind: 'EBOOK',
        completed: false,
      },
      volume: {
        id: 'volume-1',
        mediaVersionId: 'media-1',
        title: '第一卷',
        volumeIndex: 1,
        sortOrder: 0,
        format: 'EPUB',
        readerType: 'reflowable',
        derivedFromVolumeId: null,
        pageCount: 320,
        chapterCount: 2,
        durationMs: null,
        trackCount: null,
        progress: 35.5,
        lastReadAt: '2026-08-08T09:00:00Z',
      },
      availableVolumes: [
        {
          id: 'volume-1',
          mediaVersionId: 'media-1',
          title: '第一卷',
          volumeIndex: 1,
          sortOrder: 0,
          format: 'EPUB',
          readerType: 'reflowable',
          progress: 35.5,
        },
      ],
      files: [
        {
          id: 'file-1',
          kind: 'source',
          mimeType: 'application/epub+zip',
          sizeBytes: 2048,
          sortOrder: 0,
          url: '/api/files/file-1',
        },
      ],
      units: [
        {
          id: 'chapter-1',
          index: 0,
          title: '启程',
          href: 'chapter-1.xhtml',
          metadata: { level: 0 },
        },
        {
          id: 'chapter-2',
          index: 1,
          title: '远航',
          href: 'chapter-2.xhtml',
          metadata: {},
        },
      ],
      fileUrl: '/api/volumes/volume-1/file',
      capabilities: {
        canGoNext: true,
        canGoPrevious: true,
        canJumpToProgress: true,
        canJumpToHref: true,
        canJumpToIndex: true,
        canZoom: false,
        canSelectText: true,
        supportsPagination: true,
        supportsScrolling: true,
        supportsSpreads: true,
      },
      resumeLocation: {
        type: 'reflowable',
        volumeId: 'volume-1',
        format: 'epub',
        href: 'chapter-1.xhtml',
        progression: 0.35,
        foliate: {
          continuous: { sectionFraction: 0.4 },
          toc: {
            index: 0,
            title: '启程',
            href: 'chapter-1.xhtml',
            navigationKey: 'chapter-1',
          },
          navigationFingerprint: 'nav-fingerprint',
          section: { current: 1, total: 2 },
          location: { current: 10, next: 11, total: 100 },
          remainingSeconds: { section: 120, total: 600 },
        },
      },
      resumeFingerprintMismatch: false,
      progressPercent: 35.5,
    },
  };
}

test('decodes the current volume-first bootstrap contract', () => {
  const decoded = decodeReaderBootstrapResponse(bootstrapResponse());

  assert.equal(decoded.ok, true);
  if (!decoded.ok) return;
  assert.equal(decoded.value.data.book.id, 'work-1');
  assert.equal(decoded.value.data.mediaVersion.id, 'media-1');
  assert.equal(decoded.value.data.mediaVersion.workId, 'work-1');
  assert.equal(decoded.value.data.volume.id, 'volume-1');
  assert.equal(decoded.value.data.volume.mediaVersionId, 'media-1');
  assert.equal(decoded.value.data.availableVolumes[0]?.id, 'volume-1');
  assert.equal(decoded.value.data.files[0]?.url, '/api/files/file-1');
});

test('maps a relative bootstrap file URL to a reader-core source', () => {
  const decoded = decodeReaderBootstrapResponse(bootstrapResponse());
  assert.equal(decoded.ok, true);
  if (!decoded.ok) return;

  const mapped = mapReaderBootstrapToSource(
    decoded.value.data,
    'https://reader.example:8443/books',
  );

  assert.equal(mapped.ok, true);
  if (!mapped.ok) return;
  assert.deepEqual(mapped.value, {
    workId: 'work-1',
    volumeId: 'volume-1',
    contentUrl:
      'https://reader.example:8443/books/api/volumes/volume-1/file',
    contentFingerprint: 'sha256:book-content',
    totalPages: 320,
    kind: 'reflowable',
    sourceFormat: 'epub',
    navigation: [
      {
        id: 'chapter-1',
        label: '启程',
        index: 0,
        href: 'chapter-1.xhtml',
      },
      {
        id: 'chapter-2',
        label: '远航',
        index: 1,
        href: 'chapter-2.xhtml',
      },
    ],
  });
});

test('rejects a bootstrap file URL outside the connected server scope', () => {
  const decoded = decodeReaderBootstrapResponse(bootstrapResponse());
  assert.equal(decoded.ok, true);
  if (!decoded.ok) return;
  decoded.value.data.fileUrl = 'https://files.example/volume-1.epub';

  assert.deepEqual(
    mapReaderBootstrapToSource(
      decoded.value.data,
      'https://reader.example/books',
    ),
    { ok: false, reason: 'READER_V3_FILE_URL_SCOPE_MISMATCH' },
  );
});

test('preserves a valid Foliate snapshot in both mapping directions', () => {
  const decoded = decodeReaderBootstrapResponse(bootstrapResponse());
  assert.equal(decoded.ok, true);
  if (!decoded.ok) return;
  const resume = decoded.value.data.resumeLocation;
  assert.ok(resume);
  assert.equal(resume.type, 'reflowable');
  if (resume.type !== 'reflowable') return;

  const coreLocation = mapReaderLocationFromWire(resume, 'volume-1');
  assert.equal(coreLocation.ok, true);
  if (!coreLocation.ok) return;
  assert.deepEqual(coreLocation.value, {
    kind: 'reflowable',
    format: 'epub',
    href: 'chapter-1.xhtml',
    progression: 0.35,
    foliate: {
      continuous: { sectionFraction: 0.4 },
      toc: {
        index: 0,
        title: '启程',
        href: 'chapter-1.xhtml',
        navigationKey: 'chapter-1',
      },
      navigationFingerprint: 'nav-fingerprint',
      section: { current: 1, total: 2 },
      location: { current: 10, next: 11, total: 100 },
      remainingSeconds: { section: 120, total: 600 },
    },
  });

  const progress = createReaderProgressPut({
    volumeId: 'volume-1',
    mutationId: 'mutation-1',
    clientId: 'mobile-client-1',
    clientSequence: 7,
    contentFingerprint: 'sha256:book-content',
    location: coreLocation.value,
    percent: 35.5,
  });
  assert.equal(progress.ok, true);
  if (!progress.ok) return;
  assert.equal(progress.value.schemaVersion, 3);
  assert.equal(progress.value.location.type, 'reflowable');
  assert.equal(progress.value.location.volumeId, 'volume-1');
  if (progress.value.location.type !== 'reflowable') return;
  assert.deepEqual(progress.value.location.foliate, resume.foliate);
});

test('rejects invalid locations and cross-volume progress', () => {
  assert.deepEqual(
    decodeReaderLocationWire({
      type: 'reflowable',
      format: 'epub',
      foliate: {},
    }),
    { ok: false, reason: 'INVALID_READER_V3_LOCATION' },
  );
  assert.deepEqual(
    decodeReaderLocationWire({
      type: 'comic',
      volumeId: 'volume-1',
      pageIndex: 0,
    }),
    { ok: false, reason: 'INVALID_READER_V3_LOCATION' },
  );

  const invalidFoliate = decodeReaderLocationWire({
    type: 'reflowable',
    volumeId: 'volume-1',
    format: 'epub',
    progression: 0.5,
    foliate: {
      section: { current: 1, total: 1 },
      location: { current: 5, next: 4, total: 5 },
    },
  });
  assert.equal(invalidFoliate.ok, true);
  if (!invalidFoliate.ok) return;
  assert.deepEqual(
    mapReaderLocationFromWire(invalidFoliate.value, 'volume-1'),
    { ok: false, reason: 'INVALID_FOLIATE_PROGRESS_SNAPSHOT' },
  );

  const crossVolume = createReaderProgressPut({
    volumeId: 'volume-1',
    mutationId: 'mutation-2',
    clientId: 'mobile-client-1',
    clientSequence: 8,
    contentFingerprint: 'sha256:book-content',
    location: {
      kind: 'comic',
      volumeId: 'volume-2',
      pageIndex: 3,
    },
    percent: 10,
  });
  assert.deepEqual(crossVolume, {
    ok: false,
    reason: 'READER_V3_LOCATION_VOLUME_MISMATCH',
  });
});

test('rejects contract drift across work, media version, and volume', () => {
  const response = bootstrapResponse();
  response.data.volume.mediaVersionId = 'wrong-media-version-id';

  assert.deepEqual(decodeReaderBootstrapResponse(response), {
    ok: false,
    reason: 'INVALID_READER_V3_BOOTSTRAP',
  });
});

test('keeps audio explicit until reader-core gains an audio location', () => {
  const decoded = decodeReaderLocationWire({
    type: 'audio',
    volumeId: 'volume-audio',
    fileId: 'track-1',
    chapterId: 'chapter-1',
    positionMs: 1_500,
  });
  assert.equal(decoded.ok, true);
  if (!decoded.ok) return;

  assert.deepEqual(
    mapReaderLocationFromWire(decoded.value, 'volume-audio'),
    { ok: false, reason: 'READER_CORE_AUDIO_NOT_SUPPORTED' },
  );
});

test('decodes typed reader errors and rejects non-JSON details', () => {
  assert.deepEqual(
    decodeReaderErrorBody({
      message: '卷册内容已变化，请重新载入',
      code: 'CONTENT_FINGERPRINT_MISMATCH',
      details: {
        expectedContentFingerprint: 'sha256:new',
        receivedContentFingerprint: 'sha256:old',
      },
    }),
    {
      ok: true,
      value: {
        message: '卷册内容已变化，请重新载入',
        code: 'CONTENT_FINGERPRINT_MISMATCH',
        details: {
          expectedContentFingerprint: 'sha256:new',
          receivedContentFingerprint: 'sha256:old',
        },
      },
    },
  );
  assert.deepEqual(
    decodeReaderErrorBody({ message: 'bad', details: { ratio: Number.NaN } }),
    { ok: false, reason: 'INVALID_READER_V3_ERROR' },
  );
  assert.deepEqual(
    decodeReaderErrorResponse({
      ok: false,
      error: {
        message: '卷册不存在',
        code: 'VOLUME_NOT_FOUND',
      },
    }),
    {
      ok: true,
      value: {
        ok: false,
        error: {
          message: '卷册不存在',
          code: 'VOLUME_NOT_FOUND',
        },
      },
    },
  );
});

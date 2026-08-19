import assert from 'node:assert/strict';
import test from 'node:test';
import { mapWorkView, volumeFileDownloadUrl } from './client';

test('builds an explicit attachment URL for a single-volume download', () => {
  assert.equal(
    volumeFileDownloadUrl('volume/id with spaces'),
    '/api/volumes/volume%2Fid%20with%20spaces/file?download=true'
  );
});

test('full work responses reject summary projections before reaching detail UI', () => {
  assert.throws(
    () => mapWorkView({ id: 'work-1', title: 'Summary only' }),
    /版本结构/
  );
});

test('keeps server totals when the lean work detail contains only the first volume page', () => {
  const work = mapWorkView({
    id: 'work-1',
    versions: [{
      id: 'version-1',
      sourceKey: '__implicit__',
      sourceName: null,
      volumeCount: 12,
      sizeBytes: 4096,
      volumes: [{
        id: 'volume-1',
        versionId: 'version-1',
        title: 'Volume 1',
        format: 'COMIC',
        sortOrder: 0,
        sizeBytes: 1024,
        files: []
      }]
    }]
  });

  assert.equal(work.versions[0]?.volumeCount, 12);
  assert.equal(work.versions[0]?.sizeBytes, 4096);
  assert.equal(work.versions[0]?.volumes.length, 1);
  assert.equal(work.versions[0]?.volumes[0]?.readable, true);
  assert.equal(work.versions[0]?.volumes[0]?.versionId, 'version-1');
});

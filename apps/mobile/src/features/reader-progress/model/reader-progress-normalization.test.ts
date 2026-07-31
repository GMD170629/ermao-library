import assert from 'node:assert/strict';
import test from 'node:test';

import {
  recordReaderProgress,
  type ProgressConnection,
} from './reader-progress';

const connection: ProgressConnection = {
  profileId: 'profile-000001',
  baseUrl: 'https://library.example',
};

test('stores the validated normalized reader location', () => {
  const recorded = recordReaderProgress(null, {
    connection,
    owner: { kind: 'local' },
    workId: 'work-1',
    editionId: 'edition-1',
    volumeId: null,
    contentFingerprint: 'fingerprint-1',
    location: {
      kind: 'epub',
      cfi: '  epubcfi(/6/2!/4/1:0)  ',
      href: '  chapter-1.xhtml  ',
    },
    percent: 10,
    nowMs: 1_000,
    proposedClientId: 'client-1',
    mutationId: 'mutation-1',
  });

  assert.deepEqual(recorded.entry.location, {
    kind: 'reflowable',
    format: 'epub',
    cfi: 'epubcfi(/6/2!/4/1:0)',
    href: 'chapter-1.xhtml',
  });
});

import assert from 'node:assert/strict';
import test from 'node:test';
import {
  allImportExtensions,
  commonAudiobookExtensions,
  compatibilityAudiobookExtensions,
  importFileInputAccept
} from './import-formats';

test('exposes every audiobook extension through upload and preferences', () => {
  const audiobookExtensions = [
    ...commonAudiobookExtensions,
    ...compatibilityAudiobookExtensions
  ];
  assert.equal(new Set(allImportExtensions).size, allImportExtensions.length);
  assert.equal(new Set(audiobookExtensions).size, audiobookExtensions.length);
  assert.ok(audiobookExtensions.includes('.flac'));
  assert.ok(audiobookExtensions.includes('.opus'));
  assert.ok(audiobookExtensions.includes('.wma'));
  assert.ok(audiobookExtensions.includes('.xma'));
  assert.ok(audiobookExtensions.every((extension) => importFileInputAccept.includes(extension)));
});

test('does not admit generic video or DRM containers', () => {
  const supported: readonly string[] = allImportExtensions;
  for (const extension of ['.mp4', '.webm', '.mkv', '.rm', '.3gp', '.aa', '.aax', '.aaxc', '.m4p']) {
    assert.equal(supported.includes(extension), false);
  }
});

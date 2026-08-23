import assert from 'node:assert/strict';
import test from 'node:test';
import {
  READER_FORMAT_CAPABILITIES,
  parseSupportedReaderSourceFormat,
  readerFormatCapability
} from '@shuku/reader-core';

test('reader format registry is the single supported visual format matrix', () => {
  assert.deepEqual(
    READER_FORMAT_CAPABILITIES.map((entry) => entry.sourceFormat),
    ['epub', 'mobi', 'azw', 'azw3', 'prc', 'txt', 'fb2', 'cbz', 'zip', 'cbr', 'rar', 'image_dir', 'pdf']
  );
  assert.equal(readerFormatCapability('txt').readerKind, 'reflowable');
  assert.equal(readerFormatCapability('cbz').readerKind, 'comic');
  assert.equal(readerFormatCapability('pdf').readerKind, 'pdf');
});

test('format parsing is case insensitive and includes comic archive aliases', () => {
  assert.equal(parseSupportedReaderSourceFormat(' TXT '), 'txt');
  assert.equal(parseSupportedReaderSourceFormat('CBZ'), 'cbz');
  assert.equal(parseSupportedReaderSourceFormat('ZIP'), 'zip');
  assert.equal(parseSupportedReaderSourceFormat('cbr'), 'cbr');
  assert.equal(parseSupportedReaderSourceFormat('rar'), 'rar');
  assert.equal(parseSupportedReaderSourceFormat('FB2'), 'fb2');
  assert.equal(parseSupportedReaderSourceFormat('IMAGE_DIR'), 'image_dir');
  for (const value of ['', null]) {
    assert.equal(parseSupportedReaderSourceFormat(value), null);
  }
});

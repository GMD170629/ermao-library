import assert from 'node:assert/strict';
import test from 'node:test';
import {
  READER_FORMAT_CAPABILITIES,
  parseSupportedReaderSourceFormat,
  readerFormatCapability
} from '@shuku/reader-core';

test('P2 reader format registry is the single supported visual format matrix', () => {
  assert.deepEqual(
    READER_FORMAT_CAPABILITIES.map((entry) => entry.sourceFormat),
    ['epub', 'mobi', 'azw', 'azw3', 'prc', 'txt', 'cbz', 'pdf']
  );
  assert.equal(readerFormatCapability('txt').readerKind, 'reflowable');
  assert.equal(readerFormatCapability('cbz').readerKind, 'comic');
  assert.equal(readerFormatCapability('pdf').readerKind, 'pdf');
});

test('format parsing is case insensitive but does not promote unsupported containers', () => {
  assert.equal(parseSupportedReaderSourceFormat(' TXT '), 'txt');
  assert.equal(parseSupportedReaderSourceFormat('CBZ'), 'cbz');
  for (const value of ['fb2', 'zip', 'cbr', 'rar', '', null]) {
    assert.equal(parseSupportedReaderSourceFormat(value), null);
  }
});

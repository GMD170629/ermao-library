import assert from 'node:assert/strict';
import test from 'node:test';
import { structureFileLabel } from './structure-file-label';

test('audiobook structure labels hide POSIX source directories', () => {
  assert.equal(
    structureFileLabel('audio', '/monitor/listen-book/鬼吹灯/01. 精绝古城 01.mp3'),
    '01. 精绝古城 01.mp3'
  );
});

test('audiobook structure labels hide Windows source directories', () => {
  assert.equal(
    structureFileLabel('audio', String.raw`D:\audiobooks\Example\track 01.m4b`),
    'track 01.m4b'
  );
});

test('audiobook structure labels preserve a bare file name', () => {
  assert.equal(structureFileLabel('audio', 'track 01.mp3'), 'track 01.mp3');
});

test('non-audiobook structure labels retain their existing path display', () => {
  assert.equal(structureFileLabel('reflowable', '/books/example.epub'), '/books/example.epub');
  assert.equal(structureFileLabel('comic', '/comics/example.cbz'), '/comics/example.cbz');
});

import assert from 'node:assert/strict';
import test from 'node:test';
import { directoryPathChain } from './directory-path';

test('keeps the filesystem root while locating a nested monitor folder', () => {
  assert.deepEqual(directoryPathChain('/home/liumianti/books'), [
    '/',
    '/home',
    '/home/liumianti',
    '/home/liumianti/books'
  ]);
});

test('normalizes repeated separators without accepting a relative path', () => {
  assert.deepEqual(directoryPathChain('//home///books/'), ['/', '/home', '/home/books']);
  assert.deepEqual(directoryPathChain('home/books'), []);
});

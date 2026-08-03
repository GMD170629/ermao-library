import assert from 'node:assert/strict';
import test from 'node:test';
import { initialOpdsPublicBaseUrl } from './opds-settings';

test('defaults a new OPDS public URL to the current browser origin', () => {
  assert.equal(
    initialOpdsPublicBaseUrl(undefined, 'https://books.example.com'),
    'https://books.example.com'
  );
});

test('keeps an OPDS public URL previously saved by the administrator', () => {
  assert.equal(
    initialOpdsPublicBaseUrl('https://reader.example.com/library', 'https://books.example.com'),
    'https://reader.example.com/library'
  );
});

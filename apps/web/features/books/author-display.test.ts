import assert from 'node:assert/strict';
import test from 'node:test';
import { authorDisplayLabel } from '../../types/book';

test('missing authors stay blank, including the legacy placeholder', () => {
  for (const value of [undefined, null, '', '  ', '\n\t', '未知作者', ' 未知作者 ']) {
    assert.equal(authorDisplayLabel(value), '');
  }
  assert.equal(authorDisplayLabel(' 余华 '), '余华');
  assert.equal(authorDisplayLabel('Ursula K. Le Guin'), 'Ursula K. Le Guin');
});

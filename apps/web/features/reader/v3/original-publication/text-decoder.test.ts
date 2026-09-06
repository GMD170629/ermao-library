import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { decodePublicationText } from './text-decoder';

type DecodingFixture = Readonly<{
  schema: string;
  version: number;
  cases: readonly Readonly<{
    id: string;
    sourceHex: string;
    expectedText: string | null;
  }>[];
}>;

const fixture = JSON.parse(readFileSync(
  path.resolve(import.meta.dirname, '../../../../../../packages/reader-contracts/fixtures/txt-decoding-v1.json'),
  'utf8'
)) as DecodingFixture;

test('Web text decoding follows the shared txt-decoding-v1 fixture', () => {
  assert.equal(fixture.schema, 'ermao.txt-decoding');
  assert.equal(fixture.version, 1);
  for (const item of fixture.cases) {
    const source = Uint8Array.from(Buffer.from(item.sourceHex, 'hex'));
    if (item.expectedText === null) {
      assert.throws(() => decodePublicationText(source), /PUBLICATION_TXT_ENCODING_UNSUPPORTED/u, item.id);
    } else {
      assert.equal(decodePublicationText(source), item.expectedText, item.id);
    }
  }
});

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
    expectedText: string;
    decoderOverrides?: Readonly<{ 'web-textdecoder'?: Readonly<{ expectedText: string }> }>;
  }>[];
}>;

const fixture = JSON.parse(readFileSync(
  path.resolve(import.meta.dirname, '../../../../../../packages/reader-contracts/fixtures/txt-decoding-v2.json'),
  'utf8'
)) as DecodingFixture;

test('Web text decoding follows the shared txt-decoding-v2 fixture', () => {
  assert.equal(fixture.schema, 'ermao.txt-decoding');
  assert.equal(fixture.version, 2);
  for (const item of fixture.cases) {
    const source = Uint8Array.from(Buffer.from(item.sourceHex, 'hex'));
    assert.equal(decodePublicationText(source, 'txt'), item.decoderOverrides?.['web-textdecoder']?.expectedText ?? item.expectedText, item.id);
  }
});

test('FB2 retains strict decoding when TXT replaces malformed bytes', () => {
  const bytes = Uint8Array.from([0xef, 0xbb, 0xbf, 0x41, 0xff, 0x42]);
  assert.equal(decodePublicationText(bytes, 'txt'), 'A�B');
  assert.throws(() => decodePublicationText(bytes, 'fb2'), /PUBLICATION_TXT_ENCODING_UNSUPPORTED/u);
  assert.equal(decodePublicationText(new TextEncoder().encode('<FictionBook/>'), 'fb2'), '<FictionBook/>');
});

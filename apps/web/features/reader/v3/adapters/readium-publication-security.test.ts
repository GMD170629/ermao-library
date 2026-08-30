import assert from 'node:assert/strict';
import test from 'node:test';
import { BlobReader, BlobWriter, TextReader, ZipReader, ZipWriter } from '@zip.js/zip.js';
import {
  READER_SAFETY_IMPLEMENTATION_FAILURE_CODES,
  READER_SAFETY_RULE_IDS,
  ReaderSafetyImplementationError,
  ReaderSafetyPolicyError
} from '@shuku/reader-core';
import { preflightEpubArchiveEntries } from '../security/epub-archive-safety';

function findBytes(haystack: Uint8Array, needle: Uint8Array): number {
  outer: for (let offset = 0; offset <= haystack.length - needle.length; offset += 1) {
    for (let index = 0; index < needle.length; index += 1) {
      if (haystack[offset + index] !== needle[index]) continue outer;
    }
    return offset;
  }
  return -1;
}

function replaceZipCompressionMethod(bytes: Uint8Array, method: number): void {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let replacements = 0;
  for (let offset = 0; offset <= bytes.byteLength - 12; offset += 1) {
    const signature = view.getUint32(offset, true);
    if (signature === 0x04034b50) {
      view.setUint16(offset + 8, method, true);
      replacements += 1;
    } else if (signature === 0x02014b50) {
      view.setUint16(offset + 10, method, true);
      replacements += 1;
    }
  }
  assert.equal(replacements, 2);
}

test('EPUB preflight rejects a CRC failure in an unused archive entry', async () => {
  const payload = 'unused-entry-crc-payload';
  const writer = new ZipWriter(new BlobWriter('application/epub+zip'));
  await writer.add('unused.bin', new TextReader(payload), { level: 0 });
  const archive = await writer.close();
  const bytes = new Uint8Array(await archive.arrayBuffer());
  const payloadOffset = findBytes(bytes, new TextEncoder().encode(payload));
  assert.notEqual(payloadOffset, -1);
  bytes[payloadOffset] = (bytes[payloadOffset] ?? 0) ^ 0x01;

  const reader = new ZipReader(new BlobReader(
    new Blob([Uint8Array.from(bytes).buffer], { type: 'application/epub+zip' })
  ));
  try {
    const entries = await reader.getEntries({ strictness: 'strict', filenameValidation: 'strict' });
    await assert.rejects(
      preflightEpubArchiveEntries(entries),
      (reason: unknown) => reason instanceof ReaderSafetyPolicyError
        && reason.ruleId === READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE
    );
  } finally {
    await reader.close();
  }
});

test('EPUB preflight reports an unavailable compression algorithm as an engine failure', async () => {
  const writer = new ZipWriter(new BlobWriter('application/epub+zip'));
  await writer.add('unused.bin', new TextReader('unsupported-compression'), { level: 0 });
  const archive = await writer.close();
  const bytes = new Uint8Array(await archive.arrayBuffer());
  replaceZipCompressionMethod(bytes, 99);

  const reader = new ZipReader(new BlobReader(
    new Blob([Uint8Array.from(bytes).buffer], { type: 'application/epub+zip' })
  ));
  try {
    const entries = await reader.getEntries({ strictness: 'strict', filenameValidation: 'strict' });
    await assert.rejects(
      preflightEpubArchiveEntries(entries),
      (reason: unknown) => reason instanceof ReaderSafetyImplementationError
        && reason.ruleId === READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE
        && reason.code.startsWith('ENGINE_')
        && (READER_SAFETY_IMPLEMENTATION_FAILURE_CODES as readonly string[]).includes(reason.code)
    );
  } finally {
    await reader.close();
  }
});

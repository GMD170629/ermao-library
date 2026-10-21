type TextEncodingCandidate = Readonly<{
  encoding: string;
  offset: number;
}>;

function startsWith(bytes: Uint8Array, prefix: readonly number[]): boolean {
  return bytes.byteLength >= prefix.length
    && prefix.every((value, index) => bytes[index] === value);
}

/** TXT follows txt-decoding-v2; FB2 retains its strict source decoding. */
export function decodePublicationText(bytes: Uint8Array, format: 'txt' | 'fb2'): string {
  const candidates: readonly TextEncodingCandidate[] = startsWith(bytes, [0xef, 0xbb, 0xbf])
    ? [{ encoding: 'utf-8', offset: 3 }]
    : startsWith(bytes, [0xff, 0xfe])
      ? [{ encoding: 'utf-16le', offset: 2 }]
      : startsWith(bytes, [0xfe, 0xff])
        ? [{ encoding: 'utf-16be', offset: 2 }]
        : [{ encoding: 'utf-8', offset: 0 }, { encoding: 'gb18030', offset: 0 }];
  if (format === 'txt') {
    if (candidates.length === 1) {
      const candidate = candidates[0];
      return new TextDecoder(candidate.encoding, { ignoreBOM: true }).decode(bytes.subarray(candidate.offset));
    }
    try {
      return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
    } catch {
      return new TextDecoder('gb18030', { ignoreBOM: true }).decode(bytes);
    }
  }
  let lastError: unknown = null;
  for (const candidate of candidates) {
    try {
      return new TextDecoder(candidate.encoding, { fatal: true })
        .decode(bytes.subarray(candidate.offset));
    } catch (error) {
      lastError = error;
    }
  }
  throw new Error('PUBLICATION_TXT_ENCODING_UNSUPPORTED', { cause: lastError });
}

type TextEncodingCandidate = Readonly<{
  encoding: string;
  offset: number;
}>;

function startsWith(bytes: Uint8Array, prefix: readonly number[]): boolean {
  return bytes.byteLength >= prefix.length
    && prefix.every((value, index) => bytes[index] === value);
}

/** Decodes TXT/FB2 source bytes according to txt-decoding-v1. */
export function decodePublicationText(bytes: Uint8Array): string {
  const candidates: readonly TextEncodingCandidate[] = startsWith(bytes, [0xef, 0xbb, 0xbf])
    ? [{ encoding: 'utf-8', offset: 3 }]
    : startsWith(bytes, [0xff, 0xfe])
      ? [{ encoding: 'utf-16le', offset: 2 }]
      : startsWith(bytes, [0xfe, 0xff])
        ? [{ encoding: 'utf-16be', offset: 2 }]
        : [{ encoding: 'utf-8', offset: 0 }, { encoding: 'gb18030', offset: 0 }];
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

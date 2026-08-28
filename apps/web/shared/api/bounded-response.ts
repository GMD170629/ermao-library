export class ResponseLimitError extends Error {
  constructor(readonly code: 'RESPONSE_TOO_LARGE' | 'RESPONSE_LENGTH_INVALID' | 'RESPONSE_STREAM_MISSING') {
    super(code);
    this.name = 'ResponseLimitError';
  }
}

/** Reads only a bounded unit. Header rejection occurs before locking or pulling the body. */
export async function readBoundedResponse(response: Response, maxBytes: number, expectedBytes?: number): Promise<Uint8Array<ArrayBuffer>> {
  const declared = response.headers.get('Content-Length');
  const length = declared === null ? null : Number(declared);
  const invalidLength = declared !== null && (!/^\d+$/.test(declared) || !Number.isSafeInteger(length));
  if (invalidLength || (expectedBytes !== undefined && length !== null && length !== expectedBytes)) {
    await response.body?.cancel();
    throw new ResponseLimitError('RESPONSE_LENGTH_INVALID');
  }
  if ((length !== null && length > maxBytes) || (expectedBytes !== undefined && expectedBytes > maxBytes)) {
    await response.body?.cancel();
    throw new ResponseLimitError('RESPONSE_TOO_LARGE');
  }
  if (!response.body) throw new ResponseLimitError('RESPONSE_STREAM_MISSING');
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      size += next.value.byteLength;
      if (size > maxBytes) throw new ResponseLimitError('RESPONSE_TOO_LARGE');
      if (size > (expectedBytes ?? length ?? maxBytes)) throw new ResponseLimitError('RESPONSE_LENGTH_INVALID');
      chunks.push(next.value);
    }
    if (size !== (expectedBytes ?? length ?? size)) throw new ResponseLimitError('RESPONSE_LENGTH_INVALID');
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return bytes;
  } catch (error) {
    await reader.cancel(error);
    throw error;
  } finally { reader.releaseLock(); }
}

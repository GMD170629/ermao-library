import { sha256 } from '@noble/hashes/sha2.js';

/** Identical WASM artifact checks in HTTP pages and workers, without WebCrypto. */
export function sha256Hex(bytes: ArrayBuffer): string {
  return [...sha256(new Uint8Array(bytes))].map((value) => value.toString(16).padStart(2, '0')).join('');
}

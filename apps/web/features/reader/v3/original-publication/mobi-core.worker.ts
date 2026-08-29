/// <reference lib="webworker" />

import type {
  MobiOpenResult,
  MobiResourceDescriptor,
  MobiTocEntry,
  MobiWorkerRequest,
  MobiWorkerResponse
} from './mobi-worker-protocol';

const ABI_VERSION = 1;
const MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024;
const MAX_RESOURCE_BYTES = 256 * 1024 * 1024;
const INDEX_NONE = 0xffff_ffff;
const RUNTIME_URL = '/vendor/mobi-core/ermao-mobi.mjs';
const MANIFEST_URL = '/vendor/mobi-core/artifact-manifest.json';

type RuntimeRecord = Record<string, unknown>;

let runtimePromise: Promise<RuntimeRecord> | null = null;
let runtime: RuntimeRecord | null = null;
let bookPointer = 0;
let mounted = false;

function record(value: unknown): RuntimeRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as RuntimeRecord
    : {};
}

function numberValue(value: unknown, code = 'MOBI_WASM_PROTOCOL_INVALID'): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) throw new Error(code);
  return value;
}

function invoke(owner: RuntimeRecord, name: string, args: readonly unknown[]): unknown {
  const operation = owner[name];
  if (typeof operation !== 'function') throw new Error('MOBI_WASM_ABI_INVALID');
  return Reflect.apply(operation, owner, args);
}

function ccall(name: string, returnType: 'number' | 'string' | null, argTypes: readonly string[], args: readonly unknown[]): unknown {
  const active = runtime;
  if (!active) throw new Error('MOBI_WASM_NOT_READY');
  return invoke(active, 'ccall', [name, returnType, [...argTypes], [...args]]);
}

function malloc(size: number): number {
  const active = runtime;
  if (!active) throw new Error('MOBI_WASM_NOT_READY');
  return numberValue(invoke(active, '_malloc', [size]));
}

function free(pointer: number): void {
  if (!pointer || !runtime) return;
  invoke(runtime, '_free', [pointer]);
}

function getValue(pointer: number, type: 'i32'): number {
  if (!runtime) throw new Error('MOBI_WASM_NOT_READY');
  return numberValue(invoke(runtime, 'getValue', [pointer, type]));
}

function setValue(pointer: number, value: number, type: 'i32'): void {
  if (!runtime) throw new Error('MOBI_WASM_NOT_READY');
  invoke(runtime, 'setValue', [pointer, value, type]);
}

function u64(pointer: number): number {
  const low = getValue(pointer, 'i32') >>> 0;
  const high = getValue(pointer + 4, 'i32') >>> 0;
  const value = low + high * 0x1_0000_0000;
  if (!Number.isSafeInteger(value)) throw new Error('MOBI_WASM_INTEGER_OVERFLOW');
  return value;
}

function assertStatus(status: unknown): void {
  const value = numberValue(status);
  if (value === 0) return;
  const name = ccall('ermao_mobi_status_name', 'string', ['number'], [value]);
  const stableName = typeof name === 'string'
    ? name.toUpperCase().replace(/[^A-Z0-9]+/g, '_')
    : null;
  throw new Error(stableName ? `MOBI_${stableName}` : `MOBI_STATUS_${value}`);
}

function copyString(functionName: string, prefix: readonly number[]): string | null {
  const requiredPointer = malloc(4);
  try {
    setValue(requiredPointer, 0, 'i32');
    const first = numberValue(ccall(functionName, 'number', [...prefix.map(() => 'number'), 'number', 'number', 'number'], [...prefix, 0, 0, requiredPointer]));
    if (first !== 0 && first !== 13) assertStatus(first);
    const required = getValue(requiredPointer, 'i32') >>> 0;
    if (required <= 1) return null;
    if (required > MAX_RESOURCE_BYTES) throw new Error('MOBI_STRING_LIMIT');
    const buffer = malloc(required);
    try {
      assertStatus(ccall(functionName, 'number', [...prefix.map(() => 'number'), 'number', 'number', 'number'], [...prefix, buffer, required, requiredPointer]));
      if (!runtime) throw new Error('MOBI_WASM_NOT_READY');
      const decoded = invoke(runtime, 'UTF8ToString', [buffer, required]);
      return typeof decoded === 'string' ? decoded : null;
    } finally {
      free(buffer);
    }
  } finally {
    free(requiredPointer);
  }
}

async function sha256(bytes: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('');
}

async function loadRuntime(): Promise<RuntimeRecord> {
  if (runtimePromise) return runtimePromise;
  runtimePromise = (async () => {
    const manifestResponse = await fetch(MANIFEST_URL, { cache: 'no-store', credentials: 'same-origin' });
    const manifestValue: unknown = await manifestResponse.json().catch(() => null);
    const manifest = record(manifestValue);
    if (!manifestResponse.ok || manifest.schemaVersion !== 1 || manifest.abiVersion !== ABI_VERSION || manifest.emscriptenVersion !== '3.1.74') {
      throw new Error('MOBI_WASM_MANIFEST_INVALID');
    }
    const expectedWasmHash = typeof manifest.wasmSha256 === 'string' ? manifest.wasmSha256 : '';
    const wasmResponse = await fetch('/vendor/mobi-core/ermao-mobi.wasm', { cache: 'no-store', credentials: 'same-origin' });
    const wasmBinary = await wasmResponse.arrayBuffer();
    if (!wasmResponse.ok || !/^[a-f0-9]{64}$/.test(expectedWasmHash) || await sha256(wasmBinary) !== expectedWasmHash) {
      throw new Error('MOBI_WASM_INTEGRITY_INVALID');
    }
    const namespaceValue: unknown = await import(/* webpackIgnore: true */ RUNTIME_URL);
    const factory = record(namespaceValue).default;
    if (typeof factory !== 'function') throw new Error('MOBI_WASM_MODULE_INVALID');
    const created: unknown = await Reflect.apply(factory, undefined, [{ wasmBinary, noInitialRun: true }]);
    const createdRuntime = record(created);
    const version = invoke(createdRuntime, 'ccall', ['ermao_mobi_abi_version', 'number', [], []]);
    if (version !== ABI_VERSION) throw new Error('MOBI_WASM_ABI_INVALID');
    runtime = createdRuntime;
    return createdRuntime;
  })();
  return runtimePromise;
}

function filesystem(): RuntimeRecord {
  if (!runtime) throw new Error('MOBI_WASM_NOT_READY');
  return record(runtime.FS);
}

function closeBook(): void {
  if (bookPointer) {
    const pointer = malloc(4);
    try {
      setValue(pointer, bookPointer, 'i32');
      ccall('ermao_mobi_close', null, ['number'], [pointer]);
    } finally {
      free(pointer);
      bookPointer = 0;
    }
  }
  if (mounted) {
    invoke(filesystem(), 'unmount', ['/book']);
    mounted = false;
  }
}

function validFilename(value: string): boolean {
  return /^[a-zA-Z0-9_.-]+$/.test(value) && !value.startsWith('.');
}

async function openBook(blob: Blob, filename: string): Promise<MobiOpenResult> {
  if (blob.size <= 0 || blob.size > MAX_FILE_BYTES || !validFilename(filename)) throw new Error('MOBI_INPUT_INVALID');
  await loadRuntime();
  closeBook();
  const fs = filesystem();
  const analysis = record(invoke(fs, 'analyzePath', ['/book']));
  if (analysis.exists !== true) invoke(fs, 'mkdir', ['/book']);
  const filesystems = record(fs.filesystems);
  const workerFs = filesystems.WORKERFS;
  if (!workerFs) throw new Error('MOBI_WORKERFS_UNAVAILABLE');
  invoke(fs, 'mount', [workerFs, { blobs: [{ name: filename, data: blob }] }, '/book']);
  mounted = true;
  const options = malloc(16);
  const outBook = malloc(4);
  try {
    ccall('ermao_mobi_default_options', null, ['number'], [options]);
    setValue(options + 4, 256 * 1024, 'i32');
    setValue(options + 8, blob.size, 'i32');
    setValue(options + 12, 0, 'i32');
    setValue(outBook, 0, 'i32');
    assertStatus(ccall('ermao_mobi_open', 'number', ['string', 'number', 'number'], [`/book/${filename}`, options, outBook]));
    bookPointer = getValue(outBook, 'i32');
  } finally {
    free(options);
    free(outBook);
  }
  if (!bookPointer) throw new Error('MOBI_OPEN_FAILED');
  const info = malloc(32);
  const countPointer = malloc(4);
  try {
    setValue(info, 32, 'i32');
    assertStatus(ccall('ermao_mobi_get_book_info', 'number', ['number', 'number'], [bookPointer, info]));
    const resourceCount = getValue(info + 12, 'i32') >>> 0;
    const resources: MobiResourceDescriptor[] = [];
    for (let index = 0; index < resourceCount; index += 1) {
      const resourceInfo = malloc(24);
      try {
        setValue(resourceInfo, 24, 'i32');
        assertStatus(ccall('ermao_mobi_get_resource_info', 'number', ['number', 'number', 'number'], [bookPointer, index, resourceInfo]));
        const decodedLength = u64(resourceInfo + 16);
        if (decodedLength > MAX_RESOURCE_BYTES) throw new Error('MOBI_RESOURCE_LIMIT');
        resources.push({
          index,
          category: getValue(resourceInfo + 4, 'i32') >>> 0,
          sourceName: copyString('ermao_mobi_copy_resource_source_name', [bookPointer, index]) ?? `resource-${index}`,
          mediaType: copyString('ermao_mobi_copy_resource_media_type', [bookPointer, index]) ?? 'application/octet-stream',
          decodedLength
        });
      } finally {
        free(resourceInfo);
      }
    }
    setValue(countPointer, 0, 'i32');
    assertStatus(ccall('ermao_mobi_reading_order_count', 'number', ['number', 'number'], [bookPointer, countPointer]));
    const readingOrderCount = getValue(countPointer, 'i32') >>> 0;
    const readingOrder: number[] = [];
    for (let position = 0; position < readingOrderCount; position += 1) {
      assertStatus(ccall('ermao_mobi_reading_order_resource_index', 'number', ['number', 'number', 'number'], [bookPointer, position, countPointer]));
      readingOrder.push(getValue(countPointer, 'i32') >>> 0);
    }
    assertStatus(ccall('ermao_mobi_toc_count', 'number', ['number', 'number'], [bookPointer, countPointer]));
    const tocCount = getValue(countPointer, 'i32') >>> 0;
    const toc: MobiTocEntry[] = [];
    for (let index = 0; index < tocCount; index += 1) {
      const tocInfo = malloc(12);
      try {
        setValue(tocInfo, 12, 'i32');
        assertStatus(ccall('ermao_mobi_get_toc_info', 'number', ['number', 'number', 'number'], [bookPointer, index, tocInfo]));
        const parentIndex = getValue(tocInfo + 4, 'i32') >>> 0;
        toc.push({
          title: copyString('ermao_mobi_copy_toc_title', [bookPointer, index]) ?? `Section ${index + 1}`,
          resourceIndex: getValue(tocInfo + 8, 'i32') >>> 0,
          fragment: copyString('ermao_mobi_copy_toc_fragment', [bookPointer, index]),
          parentIndex: parentIndex === INDEX_NONE ? null : parentIndex
        });
      } finally {
        free(tocInfo);
      }
    }
    return {
      title: copyString('ermao_mobi_copy_metadata', [bookPointer, 1]),
      language: copyString('ermao_mobi_copy_metadata', [bookPointer, 4]),
      resources,
      readingOrder,
      toc
    };
  } catch (cause) {
    closeBook();
    throw cause;
  } finally {
    free(info);
    free(countPointer);
  }
}

function readResource(resourceIndex: number): ArrayBuffer {
  if (!bookPointer || !Number.isSafeInteger(resourceIndex) || resourceIndex < 0) throw new Error('MOBI_RESOURCE_INVALID');
  const info = malloc(24);
  try {
    setValue(info, 24, 'i32');
    assertStatus(ccall('ermao_mobi_get_resource_info', 'number', ['number', 'number', 'number'], [bookPointer, resourceIndex, info]));
    const length = u64(info + 16);
    if (length > MAX_RESOURCE_BYTES) throw new Error('MOBI_RESOURCE_LIMIT');
    const output = new Uint8Array(length);
    const buffer = malloc(Math.min(256 * 1024, Math.max(1, length)));
    const outRead = malloc(4);
    try {
      let offset = 0;
      while (offset < length) {
        const capacity = Math.min(256 * 1024, length - offset);
        setValue(outRead, 0, 'i32');
        const offsetLow = offset >>> 0;
        const offsetHigh = Math.floor(offset / 0x1_0000_0000) >>> 0;
        assertStatus(ccall(
          'ermao_mobi_web_read_resource',
          'number',
          ['number', 'number', 'number', 'number', 'number', 'number', 'number'],
          [bookPointer, resourceIndex, offsetLow, offsetHigh, buffer, capacity, outRead]
        ));
        const read = getValue(outRead, 'i32') >>> 0;
        if (read === 0 || read > capacity) throw new Error('MOBI_RESOURCE_READ_INVALID');
        const heap = runtime?.HEAPU8;
        if (!(heap instanceof Uint8Array)) throw new Error('MOBI_WASM_MEMORY_INVALID');
        output.set(heap.subarray(buffer, buffer + read), offset);
        offset += read;
      }
    } finally {
      free(buffer);
      free(outRead);
    }
    return output.buffer;
  } finally {
    free(info);
  }
}

function request(value: unknown): MobiWorkerRequest | null {
  const item = record(value);
  if (!Number.isSafeInteger(item.requestId) || typeof item.type !== 'string') return null;
  const requestId = Number(item.requestId);
  if (item.type === 'open' && item.blob instanceof Blob && typeof item.filename === 'string') return { requestId, type: 'open', blob: item.blob, filename: item.filename };
  if (item.type === 'read' && Number.isSafeInteger(item.resourceIndex)) return { requestId, type: 'read', resourceIndex: Number(item.resourceIndex) };
  if (item.type === 'close') return { requestId, type: 'close' };
  return null;
}

function respond(value: MobiWorkerResponse, transfer: Transferable[] = []): void {
  self.postMessage(value, transfer);
}

self.addEventListener('message', (event: MessageEvent<unknown>) => {
  const incoming = request(event.data);
  if (!incoming) return;
  void (async () => {
    if (incoming.type === 'open') {
      const result = await openBook(incoming.blob, incoming.filename);
      respond({ requestId: incoming.requestId, ok: true, type: 'open', result });
      return;
    }
    if (incoming.type === 'read') {
      const bytes = readResource(incoming.resourceIndex);
      respond({ requestId: incoming.requestId, ok: true, type: 'read', bytes }, [bytes]);
      return;
    }
    closeBook();
    respond({ requestId: incoming.requestId, ok: true, type: 'close' });
  })().catch((reason) => {
    const code = reason instanceof Error ? reason.message : 'MOBI_WORKER_FAILED';
    respond({ requestId: incoming.requestId, ok: false, code });
  });
});

import type { LocalPublicationTocEntry } from './local-publication';
import { requestReaderArtifact } from './api/client';
import { withBasePath } from '../../../../lib/base-path';

const ABI_VERSION = 1;
const MANIFEST_URL = '/vendor/chapter-core/artifact-manifest.json';
const RUNTIME_URL = '/vendor/chapter-core/ermao-chapters.mjs';

type RuntimeRecord = Record<string, unknown>;

export type ChapterEntry = Readonly<{
  index: number;
  parentIndex: number | null;
  navigable: boolean;
  key: string;
  title: string;
  href: string | null;
  sourceStart: number;
  sourceEnd: number;
  contentStart: number;
}>;

export type ChapterResult = Readonly<{
  entries: readonly ChapterEntry[];
  text: string;
}>;

export type ChapterXmlAttribute = Readonly<{
  name: string;
  value: string;
}>;

export type ChapterXmlEvent = Readonly<{
  kind: 'start' | 'text' | 'end';
  name?: string;
  text?: string;
  attributes?: readonly ChapterXmlAttribute[];
  targetHref?: string | null;
}>;

export type ChapterXmlFormat = 'epub-nav' | 'epub-ncx' | 'fb2';

export type ChapterMobiNode = Readonly<{
  parentIndex: number | null;
  title: string;
  targetHref: string | null;
}>;

type ChapterRuntime = RuntimeRecord;

type ChapterRuntimeFactory = (options: Readonly<{
  wasmBinary: ArrayBuffer;
  noInitialRun: boolean;
}>) => Promise<unknown>;

let runtimePromise: Promise<ChapterRuntime> | null = null;

function record(value: unknown): RuntimeRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as RuntimeRecord
    : {};
}

function numberValue(value: unknown, code = 'CHAPTER_WASM_PROTOCOL_INVALID'): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) throw new Error(code);
  return value;
}

function invoke(owner: RuntimeRecord, name: string, args: readonly unknown[]): unknown {
  const operation = owner[name];
  if (typeof operation !== 'function') throw new Error('CHAPTER_WASM_ABI_INVALID');
  return Reflect.apply(operation, owner, args);
}

function sha256(bytes: ArrayBuffer): Promise<string> {
  return crypto.subtle.digest('SHA-256', bytes).then((digest) => (
    [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('')
  ));
}

async function loadRuntime(): Promise<ChapterRuntime> {
  if (runtimePromise) return runtimePromise;
  const attempt = (async () => {
    const manifestResponse = await requestReaderArtifact(MANIFEST_URL);
    const manifest = record(await manifestResponse.json().catch(() => null));
    if (
      !manifestResponse.ok
      || manifest.schemaVersion !== 1
      || manifest.abiVersion !== ABI_VERSION
      || manifest.emscriptenVersion !== '3.1.74'
    ) {
      throw new Error('CHAPTER_WASM_MANIFEST_INVALID');
    }
    const expectedWasmHash = typeof manifest.wasmSha256 === 'string' ? manifest.wasmSha256 : '';
    const wasmResponse = await requestReaderArtifact('/vendor/chapter-core/ermao-chapters.wasm');
    const wasmBinary = await wasmResponse.arrayBuffer();
    if (
      !wasmResponse.ok
      || !/^[a-f0-9]{64}$/u.test(expectedWasmHash)
      || await sha256(wasmBinary) !== expectedWasmHash
    ) {
      throw new Error('CHAPTER_WASM_INTEGRITY_INVALID');
    }
    const namespaceValue: unknown = await import(/* webpackIgnore: true */ withBasePath(RUNTIME_URL));
    const factory = record(namespaceValue).default;
    if (typeof factory !== 'function') throw new Error('CHAPTER_WASM_MODULE_INVALID');
    const created = await (factory as ChapterRuntimeFactory)({ wasmBinary, noInitialRun: true });
    const runtime = record(created);
    const version = invoke(runtime, 'ccall', [
      'ermao_chapters_abi_version', 'number', [], []
    ]);
    if (numberValue(version) !== ABI_VERSION) throw new Error('CHAPTER_WASM_ABI_INVALID');
    return runtime;
  })();
  let retryable: Promise<ChapterRuntime>;
  retryable = attempt.catch((cause: unknown) => {
    if (runtimePromise === retryable) runtimePromise = null;
    throw cause;
  });
  runtimePromise = retryable;
  return runtimePromise;
}

function heap(runtime: ChapterRuntime): Uint8Array {
  const value = runtime.HEAPU8;
  if (!(value instanceof Uint8Array)) throw new Error('CHAPTER_WASM_MEMORY_INVALID');
  return value;
}

function malloc(runtime: ChapterRuntime, size: number): number {
  if (!Number.isSafeInteger(size) || size < 1) throw new Error('CHAPTER_WASM_ALLOCATION_INVALID');
  return numberValue(invoke(runtime, '_malloc', [size]));
}

function free(runtime: ChapterRuntime, pointer: number): void {
  if (pointer) invoke(runtime, '_free', [pointer]);
}

function getValue(runtime: ChapterRuntime, pointer: number, type: 'i32'): number {
  return numberValue(invoke(runtime, 'getValue', [pointer, type]));
}

function setValue(runtime: ChapterRuntime, pointer: number, value: number, type: 'i32'): void {
  invoke(runtime, 'setValue', [pointer, value, type]);
}

function ccall(
  runtime: ChapterRuntime,
  name: string,
  returnType: 'number' | null,
  argTypes: readonly string[],
  args: readonly unknown[]
): unknown {
  return invoke(runtime, 'ccall', [name, returnType, [...argTypes], [...args]]);
}

function writeString(
  runtime: ChapterRuntime,
  value: string | null | undefined,
  allocations: number[]
): number {
  if (value === null || value === undefined) return 0;
  const bytes = new TextEncoder().encode(value);
  const pointer = malloc(runtime, bytes.byteLength + 1);
  heap(runtime).set(bytes, pointer);
  heap(runtime)[pointer + bytes.byteLength] = 0;
  allocations.push(pointer);
  return pointer;
}

function readUtf8(runtime: ChapterRuntime, pointer: number, length: number): string {
  if (length === 0) return '';
  if (!pointer) throw new Error('CHAPTER_RESULT_STRING_INVALID');
  const bytes = heap(runtime);
  if (!Number.isSafeInteger(pointer) || pointer < 0
    || !Number.isSafeInteger(length) || length < 0
    || pointer > bytes.byteLength || length > bytes.byteLength - pointer) {
    throw new Error('CHAPTER_RESULT_TOO_LARGE');
  }
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(pointer, pointer + length));
  } catch {
    throw new Error('CHAPTER_RESULT_UTF8_INVALID');
  }
}

function readCString(runtime: ChapterRuntime, pointer: number): string {
  if (!pointer) return '';
  const bytes = heap(runtime);
  if (!Number.isSafeInteger(pointer) || pointer < 0 || pointer >= bytes.byteLength) {
    throw new Error('CHAPTER_RESULT_STRING_INVALID');
  }
  let end = pointer;
  const limit = bytes.byteLength;
  while (end < limit && bytes[end] !== 0) end += 1;
  if (end === limit) throw new Error('CHAPTER_RESULT_STRING_INVALID');
  return readUtf8(runtime, pointer, end - pointer);
}

function readUint64(runtime: ChapterRuntime, pointer: number): number {
  const low = getValue(runtime, pointer, 'i32') >>> 0;
  const high = getValue(runtime, pointer + 4, 'i32') >>> 0;
  const value = low + high * 0x1_0000_0000;
  if (!Number.isSafeInteger(value)) throw new Error('CHAPTER_RESULT_INTEGER_OVERFLOW');
  return value;
}

function uint64Parts(value: number): readonly [number, number] {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error('CHAPTER_INTEGER_INVALID');
  return [value >>> 0, Math.floor(value / 0x1_0000_0000) >>> 0];
}

function xmlFormat(format: ChapterXmlFormat): number {
  if (format === 'epub-nav') return 1;
  if (format === 'epub-ncx') return 2;
  return 3;
}

function xmlKind(kind: ChapterXmlEvent['kind']): number {
  if (kind === 'start') return 1;
  if (kind === 'text') return 2;
  return 3;
}

function copyEntry(runtime: ChapterRuntime, resultPointer: number, index: number): ChapterEntry {
  // The public entry is copied by the Web glue into 12 uint32 values so JS
  // never depends on compiler-specific struct padding or pointer alignment.
  const output = malloc(runtime, 48);
  try {
    const status = numberValue(ccall(
      runtime,
      'ermao_chapters_web_copy_entry',
      'number',
      ['number', 'number', 'number'],
      [resultPointer, index, output]
    ));
    if (status !== 0) throw new Error('CHAPTER_RESULT_ENTRY_INVALID');
    const parent = getValue(runtime, output + 4, 'i32');
    const key = readCString(runtime, getValue(runtime, output + 12, 'i32') >>> 0);
    const title = readCString(runtime, getValue(runtime, output + 16, 'i32') >>> 0);
    const hrefPointer = getValue(runtime, output + 20, 'i32') >>> 0;
    return {
      index: getValue(runtime, output, 'i32') >>> 0,
      parentIndex: parent < 0 ? null : parent,
      navigable: getValue(runtime, output + 8, 'i32') !== 0,
      key,
      title,
      href: hrefPointer ? readCString(runtime, hrefPointer) : null,
      sourceStart: readUint64(runtime, output + 24),
      sourceEnd: readUint64(runtime, output + 32),
      contentStart: readUint64(runtime, output + 40)
    };
  } finally {
    free(runtime, output);
  }
}

function readResult(runtime: ChapterRuntime, resultPointer: number): ChapterResult {
  if (!resultPointer) throw new Error('CHAPTER_RESULT_INVALID');
  const count = numberValue(ccall(runtime, 'ermao_chapters_count', 'number', ['number'], [resultPointer]));
  const entries = Array.from({ length: count }, (_, index) => copyEntry(runtime, resultPointer, index));
  const textPointer = numberValue(ccall(runtime, 'ermao_chapters_text', 'number', ['number'], [resultPointer]));
  const lengthOutput = malloc(runtime, 8);
  let textLength = 0;
  try {
    const lengthStatus = numberValue(ccall(
      runtime,
      'ermao_chapters_web_copy_text_length',
      'number',
      ['number', 'number'],
      [resultPointer, lengthOutput]
    ));
    if (lengthStatus !== 0) throw new Error('CHAPTER_RESULT_LENGTH_INVALID');
    textLength = readUint64(runtime, lengthOutput);
  } finally {
    free(runtime, lengthOutput);
  }
  return { entries, text: readUtf8(runtime, textPointer, textLength) };
}

function assertStatus(status: unknown): void {
  const value = numberValue(status);
  if (value === 0) return;
  if (value === 1) throw new Error('CHAPTER_INVALID_INPUT');
  if (value === 2) throw new Error('CHAPTER_OUT_OF_MEMORY');
  throw new Error(`CHAPTER_STATUS_${value}`);
}

async function withRuntime<T>(action: (runtime: ChapterRuntime) => T): Promise<T> {
  const runtime = await loadRuntime();
  return action(runtime);
}

function parseWithResult(
  runtime: ChapterRuntime,
  parse: (outPointer: number) => unknown,
  allocations: readonly number[]
): ChapterResult {
  const output = malloc(runtime, 4);
  let resultPointer = 0;
  try {
    setValue(runtime, output, 0, 'i32');
    assertStatus(parse(output));
    resultPointer = getValue(runtime, output, 'i32') >>> 0;
    return readResult(runtime, resultPointer);
  } finally {
    if (resultPointer) ccall(runtime, 'ermao_chapters_free', null, ['number'], [resultPointer]);
    free(runtime, output);
    for (const allocation of allocations) free(runtime, allocation);
  }
}

export async function parseTxtWithChapterCore(value: string): Promise<ChapterResult> {
  return withRuntime((runtime) => {
    const allocations: number[] = [];
    const input = new TextEncoder().encode(value);
    const bytes = malloc(runtime, input.byteLength || 1);
    if (input.byteLength > 0) heap(runtime).set(input, bytes);
    allocations.push(bytes);
    const [lengthLow, lengthHigh] = uint64Parts(input.byteLength);
    return parseWithResult(
      runtime,
      (output) => ccall(
        runtime,
        'ermao_chapters_parse_txt',
        'number',
        ['number', 'number', 'number', 'number'],
        [bytes, lengthLow, lengthHigh, output]
      ),
      allocations
    );
  });
}

export async function parseXmlWithChapterCore(
  format: ChapterXmlFormat,
  events: readonly ChapterXmlEvent[]
): Promise<ChapterResult> {
  return withRuntime((runtime) => {
    const allocations: number[] = [];
    const eventSize = 24;
    const attributeSize = 8;
    const eventPointer = malloc(runtime, Math.max(1, events.length * eventSize));
    allocations.push(eventPointer);
    events.forEach((event, index) => {
      const eventOffset = eventPointer + index * eventSize;
      const attributes = event.attributes ?? [];
      const attributePointer = attributes.length > 0
        ? malloc(runtime, attributes.length * attributeSize)
        : 0;
      if (attributePointer) allocations.push(attributePointer);
      attributes.forEach((attribute, attributeIndex) => {
        const offset = attributePointer + attributeIndex * attributeSize;
        setValue(runtime, offset, writeString(runtime, attribute.name, allocations), 'i32');
        setValue(runtime, offset + 4, writeString(runtime, attribute.value, allocations), 'i32');
      });
      setValue(runtime, eventOffset, xmlKind(event.kind), 'i32');
      setValue(runtime, eventOffset + 4, writeString(runtime, event.name, allocations), 'i32');
      setValue(runtime, eventOffset + 8, writeString(runtime, event.text, allocations), 'i32');
      setValue(runtime, eventOffset + 12, attributePointer, 'i32');
      setValue(runtime, eventOffset + 16, attributes.length, 'i32');
      setValue(runtime, eventOffset + 20, writeString(runtime, event.targetHref, allocations), 'i32');
    });
    return parseWithResult(
      runtime,
      (output) => ccall(
        runtime,
        'ermao_chapters_parse_xml',
        'number',
        ['number', 'number', 'number', 'number'],
        [xmlFormat(format), eventPointer, events.length, output]
      ),
      allocations
    );
  });
}

export async function chaptersFromMobi(
  nodes: readonly ChapterMobiNode[]
): Promise<ChapterResult> {
  return withRuntime((runtime) => {
    const allocations: number[] = [];
    const nodeSize = 12;
    const nodePointer = malloc(runtime, Math.max(1, nodes.length * nodeSize));
    allocations.push(nodePointer);
    nodes.forEach((node, index) => {
      const offset = nodePointer + index * nodeSize;
      setValue(runtime, offset, node.parentIndex ?? -1, 'i32');
      setValue(runtime, offset + 4, writeString(runtime, node.title, allocations), 'i32');
      setValue(runtime, offset + 8, writeString(runtime, node.targetHref, allocations), 'i32');
    });
    return parseWithResult(
      runtime,
      (output) => ccall(runtime, 'ermao_chapters_from_mobi', 'number', ['number', 'number', 'number'], [nodePointer, nodes.length, output]),
      allocations
    );
  });
}

export function chapterEntriesToToc(
  entries: readonly ChapterEntry[]
): LocalPublicationTocEntry[] {
  type MutableTocEntry = {
    href: string | null;
    title: string;
    navigationKey?: string;
    children?: MutableTocEntry[];
  };
  const roots: MutableTocEntry[] = [];
  const built = new Map<number, MutableTocEntry>();
  for (const [position, entry] of entries.entries()) {
    if (
      entry.index !== position
      || !/^chapter-\d+$/u.test(entry.key)
      || (entry.parentIndex !== null && (
        !Number.isSafeInteger(entry.parentIndex)
        || entry.parentIndex < 0
        || entry.parentIndex >= position
      ))
    ) throw new Error('CHAPTER_RESULT_TREE_INVALID');
    const item: MutableTocEntry = {
      href: entry.href,
      title: entry.title,
      navigationKey: entry.key
    };
    built.set(entry.index, item);
    if (entry.parentIndex === null) {
      roots.push(item);
      continue;
    }
    const parent = built.get(entry.parentIndex);
    if (!parent) throw new Error('CHAPTER_RESULT_PARENT_INVALID');
    (parent.children ??= []).push(item);
  }
  return roots;
}

export function chapterResultTextBytes(result: ChapterResult): Uint8Array {
  return new TextEncoder().encode(result.text);
}

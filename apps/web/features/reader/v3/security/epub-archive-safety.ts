import {
  ERR_RESERVED_COMPRESSION_METHOD,
  ERR_UNDEFINED_COMPRESSION_METHOD,
  ERR_UNSUPPORTED_COMPRESSION,
  type Entry,
  type FileEntry
} from '@zip.js/zip.js';
import {
  evaluateReaderSafety,
  readerSafetyRule,
  READER_SAFETY_BUDGETS,
  READER_SAFETY_RULE_IDS
} from '@shuku/reader-core';
import {
  ReaderSafetyPolicyError,
  readerSafetyEngineAlgorithmUnsupported,
  readerSafetyPlatformAlgorithmUnsupported,
  rejectReaderSafety
} from './reader-safety-policy';

const UNSUPPORTED_COMPRESSION_MESSAGES = new Set([
  ERR_RESERVED_COMPRESSION_METHOD,
  ERR_UNDEFINED_COMPRESSION_METHOD,
  ERR_UNSUPPORTED_COMPRESSION
]);

function optionalResourceCanBeIsolated(): boolean {
  const ruleId = READER_SAFETY_RULE_IDS.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE;
  const rule = readerSafetyRule(ruleId);
  const [decision] = evaluateReaderSafety({
    format: 'EPUB',
    resourceRole: 'OPTIONAL_RESOURCE',
    facts: [rule.trigger],
    enforcementAvailable: true,
    canIsolate: true
  });
  if (!decision || decision.action === 'REJECT_PUBLICATION') {
    readerSafetyPlatformAlgorithmUnsupported(ruleId);
  }
  return decision.action === 'BLOCK_RESOURCE' || decision.action === 'SANITIZE';
}

function archiveEntryCanBeIsolated(): boolean {
  const ruleId = READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE;
  const rule = readerSafetyRule(ruleId);
  const [decision] = evaluateReaderSafety({
    format: 'EPUB',
    resourceRole: 'OPTIONAL_RESOURCE',
    facts: [rule.trigger],
    enforcementAvailable: true,
    canIsolate: true
  });
  if (!decision || decision.action === 'REJECT_PUBLICATION') {
    readerSafetyPlatformAlgorithmUnsupported(ruleId);
  }
  return decision.action === 'SANITIZE' || decision.action === 'BLOCK_RESOURCE';
}

export function rejectUnreadableEpubResource(cause?: unknown): never {
  const ruleId = READER_SAFETY_RULE_IDS.EPUB_RESOURCE_INTEGRITY;
  const rule = readerSafetyRule(ruleId);
  const [decision] = evaluateReaderSafety({
    format: 'EPUB',
    resourceRole: 'READING_ORDER',
    facts: [rule.trigger],
    enforcementAvailable: true,
    canIsolate: false
  });
  if (!decision || decision.ruleId !== ruleId || decision.action !== 'REJECT_PUBLICATION') {
    readerSafetyPlatformAlgorithmUnsupported(ruleId);
  }
  rejectReaderSafety(ruleId, cause === undefined ? undefined : { cause });
}

/**
 * Maps a failure while reading an already indexed archive entry to the
 * generated integrity or optional-resource decision. Archive preflight has
 * already separated unsupported engines from damaged entries; this helper
 * keeps a later lazy read on the same classification boundary.
 */
export function rejectEpubResourceReadFailure(
  cause: unknown,
  requiredResource: boolean
): never {
  if (cause instanceof Error && UNSUPPORTED_COMPRESSION_MESSAGES.has(cause.message)) {
    readerSafetyEngineAlgorithmUnsupported(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE, { cause });
  }
  if (requiredResource) rejectUnreadableEpubResource(cause);
  const ruleId = READER_SAFETY_RULE_IDS.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE;
  if (!optionalResourceCanBeIsolated()) readerSafetyPlatformAlgorithmUnsupported(ruleId);
  rejectReaderSafety(ruleId, { cause });
}

export function normalizeEpubArchivePath(value: string): string {
  const slashNormalized = value.replaceAll('\\', '/');
  if (!value || value.includes('\0') || slashNormalized.startsWith('/') || /^[a-z]:/i.test(slashNormalized)) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE);
  }
  const segments: string[] = [];
  for (const segment of slashNormalized.split('/')) {
    if (!segment || segment === '.') continue;
    if (segment === '..') {
      if (segments.length === 0) {
        rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE);
      }
      segments.pop();
      continue;
    }
    segments.push(segment);
  }
  if (segments.length === 0) rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE);
  return segments.join('/');
}

function fileEntry(entry: Entry): entry is FileEntry {
  return entry.directory === false;
}

function canonicalArchiveEntryPath(entry: Entry): string {
  const filename = entry.directory && entry.filename.endsWith('/')
    ? entry.filename.slice(0, -1)
    : entry.filename;
  return normalizeEpubArchivePath(filename);
}

/**
 * Reads one indexed entry through zip.js's strict integrity checks. Archive
 * metadata is preflighted without inflating every entry; this is the single
 * lazy read path used by the publication adapter and conformance runner.
 */
export async function readEpubArchiveEntry(
  entry: FileEntry,
  requiredResource: boolean,
  signal?: AbortSignal
): Promise<Uint8Array> {
  let buffer: ArrayBuffer;
  try {
    buffer = await entry.arrayBuffer({
      signal,
      strictness: 'strict',
      checkLocalDirectory: true,
      checkCrc32: true,
      checkOverlappingEntry: true
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    rejectEpubResourceReadFailure(cause, requiredResource);
  }
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength !== entry.uncompressedSize) {
    rejectEpubResourceReadFailure(new Error('EPUB_RESOURCE_LENGTH_MISMATCH'), requiredResource);
  }
  return bytes;
}

export type EpubArchivePreflightResult = Readonly<{
  entries: ReadonlyMap<string, FileEntry>;
  unreadablePaths: ReadonlySet<string>;
}>;

/**
 * Detects EPUB archive metadata before any package or markup parser runs.
 * Content integrity is checked lazily by readEpubArchiveEntry when a resource
 * is actually accessed, preserving the same generated decision boundary for
 * required and optional resources.
 */
export async function preflightEpubArchiveEntries(
  rawEntries: readonly Entry[],
  signal?: AbortSignal
): Promise<EpubArchivePreflightResult> {
  void signal;
  if (rawEntries.length === 0) throw new Error('PUBLICATION_STRUCTURE_INVALID');
  const isolateOptionalResources = optionalResourceCanBeIsolated();
  if (rawEntries.length > READER_SAFETY_BUDGETS.archiveEntryMaxCount) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_ENTRY_MAX_COUNT);
  }
  const byPath = new Map<string, FileEntry>();
  const unreadablePaths = new Set<string>();
  const duplicatePaths = new Set<string>();
  const canonicalPaths = new Set<string>();
  const isolateUnsafeEntries = archiveEntryCanBeIsolated();
  let fileEntryCount = 0;
  let totalExpanded = 0;
  for (const entry of rawEntries) {
    let path: string | null = null;
    try {
      path = canonicalArchiveEntryPath(entry);
    } catch (cause) {
      if (!(cause instanceof ReaderSafetyPolicyError)
        || cause.ruleId !== READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE
        || !isolateUnsafeEntries) throw cause;
      // Keep scanning to preserve archive budgets and allow required-resource
      // lookup to reject explicitly when it asks for this unreadable entry.
      if (fileEntry(entry)) fileEntryCount += 1;
    }
    if (entry.uncompressedSize > READER_SAFETY_BUDGETS.archiveEntryMaxBytes) {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_ENTRY_MAX_BYTES);
    }
    if (
      entry.uncompressedSize > 0
      && (
        entry.compressedSize <= 0
        || entry.uncompressedSize / entry.compressedSize > READER_SAFETY_BUDGETS.archiveCompressionRatioMax
      )
    ) {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_COMPRESSION_RATIO);
    }
    totalExpanded += entry.uncompressedSize;
    if (totalExpanded > READER_SAFETY_BUDGETS.archiveExpandedMaxBytes) {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_EXPANDED_MAX_BYTES);
    }
    if (entry.symlink) {
      if (!isolateUnsafeEntries) rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE);
      if (fileEntry(entry)) fileEntryCount += path === null ? 0 : 1;
      if (path !== null) unreadablePaths.add(path);
      continue;
    }
    if (path === null) continue;
    if (canonicalPaths.has(path)) {
      if (!isolateOptionalResources) rejectUnreadableEpubResource();
      duplicatePaths.add(path);
      unreadablePaths.add(path);
      byPath.delete(path);
      continue;
    }
    canonicalPaths.add(path);
    if (fileEntry(entry)) {
      fileEntryCount += 1;
      // Keep encrypted entries indexed. Decryption support is decided by the
      // actual read path so required and optional roles receive the generated
      // outcome from the concrete decoder cause.
      byPath.set(path, entry);
    }
  }
  if (fileEntryCount === 0) throw new Error('PUBLICATION_STRUCTURE_INVALID');
  return { entries: byPath, unreadablePaths };
}

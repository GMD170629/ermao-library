import {
  ERR_RESERVED_COMPRESSION_METHOD,
  ERR_UNDEFINED_COMPRESSION_METHOD,
  ERR_UNSUPPORTED_COMPRESSION,
  type Entry,
  type FileEntry
} from '@zip.js/zip.js';
import {
  READER_SAFETY_BUDGETS,
  READER_SAFETY_RULE_IDS
} from '@shuku/reader-core';
import {
  readerSafetyEngineAlgorithmUnsupported,
  rejectReaderSafety
} from './reader-safety-policy';

const UNSUPPORTED_COMPRESSION_MESSAGES = new Set([
  ERR_RESERVED_COMPRESSION_METHOD,
  ERR_UNDEFINED_COMPRESSION_METHOD,
  ERR_UNSUPPORTED_COMPRESSION
]);

export function normalizeEpubArchivePath(value: string): string {
  if (!value || value.includes('\\') || value.includes('\0') || value.startsWith('/') || /^[a-z]:/i.test(value)) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE);
  }
  const segments = value.split('/');
  if (segments.some((segment) => segment === '' || segment === '.' || segment === '..')) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE);
  }
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

async function verifyZipEntry(entry: FileEntry, signal?: AbortSignal): Promise<void> {
  let writtenBytes = 0;
  try {
    await entry.getData(new WritableStream<Uint8Array>({
      write(chunk) {
        writtenBytes += chunk.byteLength;
      }
    }), {
      signal,
      strictness: 'strict',
      checkLocalDirectory: true,
      checkCrc32: true,
      checkOverlappingEntry: true
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    if (cause instanceof Error && UNSUPPORTED_COMPRESSION_MESSAGES.has(cause.message)) {
      readerSafetyEngineAlgorithmUnsupported(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE, { cause });
    }
    rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE, { cause });
  }
  if (writtenBytes !== entry.uncompressedSize) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE);
  }
}

/**
 * Detects EPUB archive facts before any package or markup parser runs. It reads
 * every file through zip.js so CRC and overlap failures in unused entries cannot
 * evade the generated publication-level policy.
 */
export async function preflightEpubArchiveEntries(
  rawEntries: readonly Entry[],
  signal?: AbortSignal
): Promise<ReadonlyMap<string, FileEntry>> {
  if (rawEntries.length === 0) throw new Error('PUBLICATION_STRUCTURE_INVALID');
  if (rawEntries.length > READER_SAFETY_BUDGETS.archiveEntryMaxCount) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_ENTRY_MAX_COUNT);
  }
  const byPath = new Map<string, FileEntry>();
  const canonicalPaths = new Set<string>();
  const files: FileEntry[] = [];
  let totalExpanded = 0;
  for (const entry of rawEntries) {
    const path = canonicalArchiveEntryPath(entry);
    if (entry.encrypted || entry.symlink || canonicalPaths.has(path)) {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE);
    }
    canonicalPaths.add(path);
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
    if (fileEntry(entry)) {
      files.push(entry);
      byPath.set(path, entry);
    }
  }
  if (files.length === 0) throw new Error('PUBLICATION_STRUCTURE_INVALID');
  for (const entry of files) await verifyZipEntry(entry, signal);
  return byPath;
}

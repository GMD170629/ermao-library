import type { ValidationResult } from '../../../shared/validation/unknown';
import {
  finiteNumberInRange,
  hasOnlyKeys,
  isRecord,
  nonEmptyString,
  nonNegativeSafeInteger,
} from '../../../shared/validation/unknown';
import type {
  CollectionDetail,
  ContinueReadingBook,
  HomeSummary,
  ImportSuccess,
  ImportTargets,
  LibraryBook,
  LibraryMediaKind,
  LibraryPreferences,
  ShelfOverviewData,
  ShelfSummary,
} from '../model/library';
import { isImportTargetPathWithinRoot } from '../model/library';
import type { BooksPage } from '../application/ports';

const ENVELOPE_KEYS = new Set(['ok', 'data']);
const ERROR_ENVELOPE_KEYS = new Set(['ok', 'error']);
const ERROR_KEYS = new Set(['message', 'code', 'details']);
const SUMMARY_KEYS = new Set([
  'totalBooks', 'ebookBooks', 'comicBooks', 'audiobookBooks',
  'storageUsedBytes', 'monitorFolderCount', 'lastImportAt', 'latestSyncAt',
]);
const CONTINUE_PAYLOAD_KEYS = new Set(['item']);
const CONTINUE_KEYS = new Set([
  'workId', 'title', 'author', 'coverUrl', 'mediaKind', 'volumeFormat',
  'readerType', 'resumeVolumeId', 'progress', 'chapter', 'lastReadAt',
  'volumeTitle', 'narrator',
]);
const WORKS_KEYS = new Set(['books', 'page', 'pageSize', 'total', 'totalPages']);
const WORK_SUMMARIES_KEYS = new Set(['books']);
const BOOK_KEYS = new Set([
  'id', 'title', 'author', 'coverUrl', 'availableMediaKinds', 'progress',
]);
const MANAGEMENT_BOOK_KEYS = new Set([
  'id', 'title', 'author', 'gradient', 'coverStatus', 'coverUrl', 'seriesName',
  'tags', 'availableMediaKinds', 'statusValue', 'lastReadAt', 'importedAt',
]);
const SHELVES_KEYS = new Set(['shelves']);
const SHELF_PAYLOAD_KEYS = new Set(['shelf']);
const DELETED_SHELF_KEYS = new Set(['deleted', 'id']);
const SHELF_KEYS = new Set([
  'id', 'ownerUserId', 'name', 'description', 'kind', 'rulesJson', 'pinned',
  'createdAt', 'updatedAt', 'rules', 'rulesStatus', 'unsupportedRuleFields',
  'bookCount', 'books', 'collectionIds', 'shelfCount', 'shelves',
  'memberShelfIds', 'page', 'pageSize', 'total', 'totalPages', 'bookIds',
]);
const SHELF_MEMBER_KEYS = new Set([
  'id', 'name', 'description', 'kind', 'pinned', 'bookCount', 'books',
  'collectionIds', 'createdAt', 'updatedAt',
]);
const SHELF_RULE_KEYS = new Set([
  'search', 'statuses', 'mediaKinds', 'tags', 'authors', 'publishers',
  'combinator', 'conditions', 'includedWorkIds',
]);
const SHELF_CONDITION_KEYS = new Set(['field', 'operator', 'value']);
const MONITOR_PAYLOAD_KEYS = new Set([
  'folders', 'monitorRoot', 'lastUploadTargetPath', 'lastDownloadTargetPath',
]);
const MONITOR_KEYS = new Set([
  'id', 'name', 'rootPath', 'shelfId', 'enabled', 'mediaKindPolicy',
  'ignorePatterns', 'ignoreHidden', 'minFileSizeBytes', 'description',
  'createdAt', 'updatedAt',
]);
const IMPORT_KEYS = new Set(['results', 'saved', 'autoImport']);
const IMPORT_RESULT_KEYS = new Set([
  'sourcePath', 'file', 'sizeBytes', 'monitoringStatus',
]);
const PREFERENCES_PAYLOAD_KEYS = new Set(['preferences']);
const PREFERENCE_KEYS = new Set([
  'locale', 'library.view', 'library.sort', 'library.sortDirection',
  'audio.playbackRate', 'kindle.email',
]);
const READER_TYPES = new Set(['audio', 'comic', 'pdf', 'reflowable']);
function isMediaKind(value: unknown): value is LibraryMediaKind {
  return typeof value === 'string' && (
    value === 'AUDIOBOOK' || value === 'COMIC' || value === 'EBOOK'
  );
}

function isReaderType(
  value: unknown,
): value is ContinueReadingBook['readerType'] {
  return typeof value === 'string' && READER_TYPES.has(value);
}

function isLibrarySort(
  value: unknown,
): value is LibraryPreferences['sort'] {
  switch (value) {
    case 'author':
    case 'recent_import':
    case 'recent_read':
    case 'series':
    case 'title':
      return true;
    default:
      return false;
  }
}

function stringValue(value: unknown, maximumLength: number): string | null {
  return typeof value === 'string' && value.length <= maximumLength
    ? value
    : null;
}

function nullableString(
  value: unknown,
  maximumLength: number,
): string | null | undefined {
  return value === null ? null : stringValue(value, maximumLength) ?? undefined;
}

function timestamp(value: unknown): string | null {
  return (
    typeof value === 'string' &&
    value.length <= 64 &&
    Number.isFinite(Date.parse(value))
  )
    ? value
    : null;
}

function nullableTimestamp(value: unknown): string | null | undefined {
  return value === null ? null : timestamp(value) ?? undefined;
}

function mediaKinds(value: unknown): readonly LibraryMediaKind[] | null {
  if (!Array.isArray(value) || value.length > 3) return null;
  const result: LibraryMediaKind[] = [];
  for (const candidate of value) {
    if (
      !isMediaKind(candidate)
    ) {
      return null;
    }
    if (!result.includes(candidate)) result.push(candidate);
  }
  return result;
}

function successData(value: unknown): unknown | undefined {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ENVELOPE_KEYS) ||
    (value.ok !== undefined && value.ok !== true) ||
    !Object.hasOwn(value, 'data')
  ) {
    return undefined;
  }
  return value.data;
}

function decodeBook(value: unknown): LibraryBook | null {
  if (!isRecord(value) || !hasOnlyKeys(value, BOOK_KEYS)) return null;
  const id = nonEmptyString(value.id, 191);
  const title = stringValue(value.title, 4_096);
  const author = stringValue(value.author, 1_024);
  const coverUrl = stringValue(value.coverUrl, 2_048);
  const kinds = mediaKinds(value.availableMediaKinds);
  const progress = value.progress === undefined
    ? undefined
    : finiteNumberInRange(value.progress, 0, 100);
  if (
    id === null || title === null || author === null || coverUrl === null ||
    kinds === null || progress === null
  ) {
    return null;
  }
  return { id, title, author, coverUrl, mediaKinds: kinds };
}

function decodeBooks(value: unknown, maximumItems: number): LibraryBook[] | null {
  if (!Array.isArray(value) || value.length > maximumItems) return null;
  const result: LibraryBook[] = [];
  for (const candidate of value) {
    const book = decodeBook(candidate);
    if (book === null) return null;
    result.push(book);
  }
  return result;
}

function optionalNullableStringArray(
  value: unknown,
  maximumItems: number,
  maximumItemLength: number,
): boolean {
  return value === undefined || value === null || (
    Array.isArray(value) && value.length <= maximumItems &&
    value.every((candidate) => stringValue(candidate, maximumItemLength) !== null)
  );
}

function shelfConditionValue(value: unknown): boolean {
  return value === undefined || value === null ||
    typeof value === 'string' || typeof value === 'boolean' ||
    (typeof value === 'number' && Number.isFinite(value)) ||
    (Array.isArray(value) && value.length <= 1_000 &&
      value.every((candidate) => typeof candidate === 'string'));
}

function validShelfRules(value: unknown): boolean {
  if (!isRecord(value) || !hasOnlyKeys(value, SHELF_RULE_KEYS) ||
      (value.search !== undefined && nullableString(value.search, 200) === undefined) ||
      !optionalNullableStringArray(value.statuses, 20, 64) ||
      !optionalNullableStringArray(value.mediaKinds, 3, 64) ||
      !optionalNullableStringArray(value.tags, 1_000, 1_024) ||
      !optionalNullableStringArray(value.authors, 1_000, 1_024) ||
      !optionalNullableStringArray(value.publishers, 1_000, 1_024) ||
      !optionalNullableStringArray(value.includedWorkIds, 10_000, 191) ||
      (value.combinator !== undefined && value.combinator !== null &&
        value.combinator !== 'ALL' && value.combinator !== 'ANY') ||
      (value.conditions !== undefined && value.conditions !== null &&
        (!Array.isArray(value.conditions) || value.conditions.length > 30))) {
    return false;
  }
  if (!Array.isArray(value.conditions)) return true;
  return value.conditions.every((condition) =>
    isRecord(condition) && hasOnlyKeys(condition, SHELF_CONDITION_KEYS) &&
    nonEmptyString(condition.field, 128) !== null &&
    nonEmptyString(condition.operator, 128) !== null &&
    shelfConditionValue(condition.value),
  );
}

function optionalNullableSafeInteger(value: unknown): boolean {
  return value === undefined || value === null ||
    nonNegativeSafeInteger(value) !== null;
}

export function decodeDashboardSummary(
  value: unknown,
): ValidationResult<Omit<HomeSummary, 'unreadBooks'>> {
  const data = successData(value);
  if (!isRecord(data) || !hasOnlyKeys(data, SUMMARY_KEYS)) {
    return { ok: false, reason: 'INVALID_DASHBOARD_SUMMARY' };
  }
  const totalBooks = nonNegativeSafeInteger(data.totalBooks);
  const ebookBooks = nonNegativeSafeInteger(data.ebookBooks);
  const comicBooks = nonNegativeSafeInteger(data.comicBooks);
  const audiobookBooks = nonNegativeSafeInteger(data.audiobookBooks);
  const storage = nonNegativeSafeInteger(data.storageUsedBytes);
  const folders = nonNegativeSafeInteger(data.monitorFolderCount);
  const lastImportAt = nullableTimestamp(data.lastImportAt);
  const latestSyncAt = nullableTimestamp(data.latestSyncAt);
  if (
    totalBooks === null || ebookBooks === null || comicBooks === null ||
    audiobookBooks === null || storage === null || folders === null ||
    lastImportAt === undefined || latestSyncAt === undefined
  ) {
    return { ok: false, reason: 'INVALID_DASHBOARD_SUMMARY' };
  }
  return {
    ok: true,
    value: { totalBooks, ebookBooks, comicBooks, audiobookBooks },
  };
}

export function decodeContinueReading(
  value: unknown,
): ValidationResult<ContinueReadingBook | null> {
  const data = successData(value);
  if (!isRecord(data) || !hasOnlyKeys(data, CONTINUE_PAYLOAD_KEYS)) {
    return { ok: false, reason: 'INVALID_CONTINUE_READING' };
  }
  if (data.item === null) return { ok: true, value: null };
  if (!isRecord(data.item) || !hasOnlyKeys(data.item, CONTINUE_KEYS)) {
    return { ok: false, reason: 'INVALID_CONTINUE_READING' };
  }
  const item = data.item;
  const id = nonEmptyString(item.workId, 191);
  const title = stringValue(item.title, 4_096);
  const author = stringValue(item.author, 1_024);
  const coverUrl = stringValue(item.coverUrl, 2_048);
  const progress = finiteNumberInRange(item.progress, 0, 100);
  const resumeVolumeId = nullableString(item.resumeVolumeId, 191);
  const chapter = nullableString(item.chapter, 4_096);
  const volumeTitle = nullableString(item.volumeTitle, 4_096);
  const lastReadAt = nullableTimestamp(item.lastReadAt);
  if (
    id === null || title === null || author === null || coverUrl === null ||
    !isMediaKind(item.mediaKind) || !isReaderType(item.readerType) ||
    progress === null || resumeVolumeId === undefined || chapter === undefined ||
    volumeTitle === undefined || lastReadAt === undefined ||
    stringValue(item.volumeFormat, 64) === null ||
    nullableString(item.narrator, 1_024) === undefined
  ) {
    return { ok: false, reason: 'INVALID_CONTINUE_READING' };
  }
  return {
    ok: true,
    value: {
      id,
      title,
      author,
      coverUrl,
      mediaKinds: [item.mediaKind],
      readerType: item.readerType,
      resumeVolumeId,
      progressPercent: progress,
      chapter,
      volumeTitle,
      lastReadAt,
    },
  };
}

export function decodeRecentBooks(
  value: unknown,
): ValidationResult<readonly LibraryBook[]> {
  const data = successData(value);
  if (!isRecord(data) || !hasOnlyKeys(data, WORK_SUMMARIES_KEYS)) {
    return { ok: false, reason: 'INVALID_RECENT_BOOKS' };
  }
  const books = decodeBooks(data.books, 20);
  return books === null
    ? { ok: false, reason: 'INVALID_RECENT_BOOKS' }
    : { ok: true, value: books };
}

export function decodeBooksPage(
  value: unknown,
): ValidationResult<BooksPage> {
  const data = successData(value);
  if (!isRecord(data) || !hasOnlyKeys(data, WORKS_KEYS)) {
    return { ok: false, reason: 'INVALID_BOOKS_PAGE' };
  }
  const books = decodeBooks(data.books, 24);
  const page = nonNegativeSafeInteger(data.page);
  const pageSize = nonNegativeSafeInteger(data.pageSize);
  const total = nonNegativeSafeInteger(data.total);
  const totalPages = nonNegativeSafeInteger(data.totalPages);
  if (
    books === null || page === null || page < 1 || pageSize !== 24 ||
    total === null || totalPages === null || totalPages < 1 || page > totalPages
  ) {
    return { ok: false, reason: 'INVALID_BOOKS_PAGE' };
  }
  return { ok: true, value: { books, page, pageSize: 24, total, totalPages } };
}

export function decodeUnreadTotal(value: unknown): ValidationResult<number> {
  const data = successData(value);
  if (!isRecord(data) || !hasOnlyKeys(data, WORKS_KEYS) ||
      !Array.isArray(data.books) || data.books.length > 1 ||
      nonNegativeSafeInteger(data.page) !== 1 ||
      nonNegativeSafeInteger(data.pageSize) !== 1) {
    return { ok: false, reason: 'INVALID_UNREAD_TOTAL' };
  }
  for (const book of data.books) {
    if (!isRecord(book) || !hasOnlyKeys(book, MANAGEMENT_BOOK_KEYS) ||
        nonEmptyString(book.id, 191) === null ||
        stringValue(book.title, 4_096) === null ||
        stringValue(book.author, 1_024) === null ||
        stringValue(book.gradient, 1_024) === null ||
        stringValue(book.coverStatus, 128) === null ||
        stringValue(book.coverUrl, 2_048) === null ||
        nullableString(book.seriesName, 1_024) === undefined ||
        !Array.isArray(book.tags) || book.tags.length > 1_000 ||
        book.tags.some((tag) => stringValue(tag, 1_024) === null) ||
        mediaKinds(book.availableMediaKinds) === null ||
        (book.statusValue !== 'UNREAD' && book.statusValue !== 'READING' &&
          book.statusValue !== 'FINISHED') ||
        nullableTimestamp(book.lastReadAt) === undefined ||
        nullableTimestamp(book.importedAt) === undefined) {
      return { ok: false, reason: 'INVALID_UNREAD_TOTAL' };
    }
  }
  const total = nonNegativeSafeInteger(data.total);
  const totalPages = nonNegativeSafeInteger(data.totalPages);
  return total === null || totalPages === null || totalPages < 1 ||
    data.books.length !== Math.min(total, 1)
    ? { ok: false, reason: 'INVALID_UNREAD_TOTAL' }
    : { ok: true, value: total };
}

function shelfSummary(value: unknown): ShelfSummary | null {
  if (!isRecord(value) || !hasOnlyKeys(value, SHELF_KEYS)) return null;
  const id = nonEmptyString(value.id, 191);
  const name = nonEmptyString(value.name, 200);
  const description = nullableString(value.description, 4_096);
  const ownerUserId = value.ownerUserId === undefined
    ? null
    : nullableString(value.ownerUserId, 191);
  const updatedAt = timestamp(value.updatedAt);
  if (
    id === null || name === null || description === undefined ||
    ownerUserId === undefined ||
    (value.kind !== 'STATIC' && value.kind !== 'SMART' &&
      value.kind !== 'COLLECTION') ||
    typeof value.pinned !== 'boolean' || updatedAt === null ||
    timestamp(value.createdAt) === null || !validShelfRules(value.rules) ||
    typeof value.rulesJson !== 'string' ||
    (value.rulesStatus !== 'VALID' && value.rulesStatus !== 'UNSUPPORTED') ||
    !Array.isArray(value.unsupportedRuleFields) ||
    value.unsupportedRuleFields.some((field) => typeof field !== 'string')
  ) {
    return null;
  }
  const books = value.books === undefined || value.books === null
    ? []
    : decodeBooks(value.books, 24);
  if (books === null) return null;
  const bookCount = value.bookCount === undefined || value.bookCount === null
    ? books.length
    : nonNegativeSafeInteger(value.bookCount);
  const shelfCount = value.shelfCount === undefined || value.shelfCount === null
    ? 0
    : nonNegativeSafeInteger(value.shelfCount);
  const memberShelfIds = value.memberShelfIds === undefined ||
      value.memberShelfIds === null
    ? []
    : value.memberShelfIds;
  const collectionIds = value.collectionIds === undefined ||
      value.collectionIds === null
    ? []
    : value.collectionIds;
  const bookIds = value.bookIds === undefined || value.bookIds === null
    ? []
    : value.bookIds;
  if (
    bookCount === null || shelfCount === null ||
    !Array.isArray(memberShelfIds) || memberShelfIds.length > 1_000 ||
    memberShelfIds.some((candidate) => nonEmptyString(candidate, 191) === null) ||
    !Array.isArray(collectionIds) || collectionIds.length > 1_000 ||
    collectionIds.some((candidate) => nonEmptyString(candidate, 191) === null) ||
    !Array.isArray(bookIds) || bookIds.length > 10_000 ||
    bookIds.some((candidate) => nonEmptyString(candidate, 191) === null) ||
    !optionalNullableSafeInteger(value.page) ||
    !optionalNullableSafeInteger(value.pageSize) ||
    !optionalNullableSafeInteger(value.total) ||
    !optionalNullableSafeInteger(value.totalPages)
  ) {
    return null;
  }
  if (value.shelves !== undefined && value.shelves !== null) {
    if (!Array.isArray(value.shelves) || value.shelves.length > 1_000) return null;
    for (const member of value.shelves) {
      if (!isRecord(member) || !hasOnlyKeys(member, SHELF_MEMBER_KEYS)) return null;
      if (
        nonEmptyString(member.id, 191) === null ||
        nonEmptyString(member.name, 200) === null ||
        (member.kind !== 'STATIC' && member.kind !== 'SMART') ||
        nonNegativeSafeInteger(member.bookCount) === null ||
        decodeBooks(member.books, 24) === null
      ) {
        return null;
      }
    }
  }
  return {
    id,
    name,
    description,
    kind: value.kind,
    pinned: value.pinned,
    bookCount,
    shelfCount,
    books,
    memberShelfIds: memberShelfIds.filter(
      (candidate): candidate is string => typeof candidate === 'string',
    ),
    updatedAt,
  };
}

function memberShelfSummary(value: unknown): ShelfSummary | null {
  if (!isRecord(value) || !hasOnlyKeys(value, SHELF_MEMBER_KEYS)) return null;
  const id = nonEmptyString(value.id, 191);
  const name = nonEmptyString(value.name, 200);
  const description = nullableString(value.description, 4_096);
  const bookCount = nonNegativeSafeInteger(value.bookCount);
  const books = decodeBooks(value.books, 24);
  const createdAt = timestamp(value.createdAt);
  const updatedAt = timestamp(value.updatedAt);
  if (
    id === null || name === null || description === undefined ||
    (value.kind !== 'STATIC' && value.kind !== 'SMART') ||
    typeof value.pinned !== 'boolean' || bookCount === null || books === null ||
    !Array.isArray(value.collectionIds) || value.collectionIds.length > 1_000 ||
    value.collectionIds.some(
      (candidate) => nonEmptyString(candidate, 191) === null,
    ) ||
    createdAt === null || updatedAt === null
  ) {
    return null;
  }
  return {
    id,
    name,
    description,
    kind: value.kind,
    pinned: value.pinned,
    bookCount,
    shelfCount: 0,
    books,
    memberShelfIds: [],
    updatedAt,
  };
}

export function decodeShelves(
  value: unknown,
): ValidationResult<ShelfOverviewData> {
  const data = successData(value);
  if (!isRecord(data) || !hasOnlyKeys(data, SHELVES_KEYS) ||
      !Array.isArray(data.shelves) || data.shelves.length > 1_000) {
    return { ok: false, reason: 'INVALID_SHELVES' };
  }
  const collections: ShelfSummary[] = [];
  const shelves: ShelfSummary[] = [];
  for (const candidate of data.shelves) {
    const shelf = shelfSummary(candidate);
    if (shelf === null) return { ok: false, reason: 'INVALID_SHELVES' };
    (shelf.kind === 'COLLECTION' ? collections : shelves).push(shelf);
  }
  return { ok: true, value: { collections, shelves } };
}

export function decodeShelf(value: unknown): ValidationResult<ShelfSummary> {
  const data = successData(value);
  if (!isRecord(data) || !hasOnlyKeys(data, SHELF_PAYLOAD_KEYS)) {
    return { ok: false, reason: 'INVALID_SHELF' };
  }
  const shelf = shelfSummary(data.shelf);
  return shelf === null
    ? { ok: false, reason: 'INVALID_SHELF' }
    : { ok: true, value: shelf };
}

export function decodeCollectionDetail(
  value: unknown,
): ValidationResult<CollectionDetail> {
  const data = successData(value);
  if (!isRecord(data) || !hasOnlyKeys(data, SHELF_PAYLOAD_KEYS) ||
      !isRecord(data.shelf)) {
    return { ok: false, reason: 'INVALID_COLLECTION_DETAIL' };
  }
  const collection = shelfSummary(data.shelf);
  if (
    collection === null || collection.kind !== 'COLLECTION' ||
    !Array.isArray(data.shelf.shelves) || data.shelf.shelves.length > 1_000
  ) {
    return { ok: false, reason: 'INVALID_COLLECTION_DETAIL' };
  }
  const shelves: ShelfSummary[] = [];
  for (const candidate of data.shelf.shelves) {
    const member = memberShelfSummary(candidate);
    if (member === null) {
      return { ok: false, reason: 'INVALID_COLLECTION_DETAIL' };
    }
    shelves.push(member);
  }
  return {
    ok: true,
    value: { id: collection.id, name: collection.name, shelves },
  };
}

export function decodeDeletedShelf(
  value: unknown,
): ValidationResult<Readonly<{ id: string }>> {
  const data = successData(value);
  if (!isRecord(data) || !hasOnlyKeys(data, DELETED_SHELF_KEYS) ||
      data.deleted !== true) {
    return { ok: false, reason: 'INVALID_DELETED_SHELF' };
  }
  const id = nonEmptyString(data.id, 191);
  return id === null
    ? { ok: false, reason: 'INVALID_DELETED_SHELF' }
    : { ok: true, value: { id } };
}

export function decodeImportTargets(
  value: unknown,
): ValidationResult<ImportTargets> {
  const data = successData(value);
  if (!isRecord(data) || !hasOnlyKeys(data, MONITOR_PAYLOAD_KEYS) ||
      !Array.isArray(data.folders) || data.folders.length > 1_000) {
    return { ok: false, reason: 'INVALID_IMPORT_TARGETS' };
  }
  const targets: ImportTargets['targets'][number][] = [];
  for (const folder of data.folders) {
    if (!isRecord(folder) || !hasOnlyKeys(folder, MONITOR_KEYS)) {
      return { ok: false, reason: 'INVALID_IMPORT_TARGETS' };
    }
    const folderId = nonEmptyString(folder.id, 191);
    const name = nonEmptyString(folder.name, 200);
    const rootPath = nonEmptyString(folder.rootPath, 4_096);
    const shelfId = folder.shelfId === undefined
      ? null
      : nullableString(folder.shelfId, 191);
    const ignorePatterns = folder.ignorePatterns === undefined
      ? null
      : nullableString(folder.ignorePatterns, 16_384);
    const description = nullableString(folder.description, 4_096);
    if (folderId === null || name === null || rootPath === null ||
        shelfId === undefined || ignorePatterns === undefined ||
        description === undefined || typeof folder.enabled !== 'boolean' ||
        (folder.mediaKindPolicy !== 'MIXED' &&
          !isMediaKind(folder.mediaKindPolicy)) ||
        typeof folder.ignoreHidden !== 'boolean' ||
        nonNegativeSafeInteger(folder.minFileSizeBytes) === null ||
        timestamp(folder.createdAt) === null || timestamp(folder.updatedAt) === null) {
      return { ok: false, reason: 'INVALID_IMPORT_TARGETS' };
    }
    if (folder.enabled) targets.push({ folderId, name, rootPath, enabled: true });
  }
  const preferred = nullableString(data.lastUploadTargetPath, 4_096);
  if (preferred === undefined) {
    return { ok: false, reason: 'INVALID_IMPORT_TARGETS' };
  }
  const selectedTargetPath =
    preferred !== null && targets.some(
      (target) => isImportTargetPathWithinRoot(preferred, target.rootPath),
    )
      ? preferred
      : targets[0]?.rootPath ?? null;
  return { ok: true, value: { targets, selectedTargetPath } };
}

export function decodeImportSuccess(
  value: unknown,
): ValidationResult<ImportSuccess> {
  const data = successData(value);
  if (!isRecord(data) || !hasOnlyKeys(data, IMPORT_KEYS) ||
      !Array.isArray(data.results) || data.results.length > 1_000) {
    return { ok: false, reason: 'INVALID_IMPORT_RESULT' };
  }
  const saved = nonNegativeSafeInteger(data.saved);
  if (saved === null || typeof data.autoImport !== 'boolean') {
    return { ok: false, reason: 'INVALID_IMPORT_RESULT' };
  }
  const files: ImportSuccess['files'][number][] = [];
  for (const result of data.results) {
    if (!isRecord(result) || !hasOnlyKeys(result, IMPORT_RESULT_KEYS)) {
      return { ok: false, reason: 'INVALID_IMPORT_RESULT' };
    }
    const sourcePath = nonEmptyString(result.sourcePath, 4_096);
    const name = nonEmptyString(result.file, 1_024);
    const sizeBytes = nonNegativeSafeInteger(result.sizeBytes);
    if (sourcePath === null || name === null || sizeBytes === null ||
        (result.monitoringStatus !== 'WATCHING' &&
          result.monitoringStatus !== 'NOT_MONITORED')) {
      return { ok: false, reason: 'INVALID_IMPORT_RESULT' };
    }
    files.push({
      name,
      sourcePath,
      sizeBytes,
      monitoringStatus: result.monitoringStatus,
    });
  }
  if (saved !== files.length) {
    return { ok: false, reason: 'INVALID_IMPORT_RESULT' };
  }
  return { ok: true, value: { saved, autoImport: data.autoImport, files } };
}

export function decodePreferences(
  value: unknown,
): ValidationResult<LibraryPreferences> {
  const data = successData(value);
  if (!isRecord(data) || !hasOnlyKeys(data, PREFERENCES_PAYLOAD_KEYS) ||
      !isRecord(data.preferences) ||
      !hasOnlyKeys(data.preferences, PREFERENCE_KEYS)) {
    return { ok: false, reason: 'INVALID_LIBRARY_PREFERENCES' };
  }
  const view = data.preferences['library.view'];
  const sort = data.preferences['library.sort'];
  const direction = data.preferences['library.sortDirection'];
  const locale = data.preferences.locale;
  const playbackRate = data.preferences['audio.playbackRate'];
  const kindleEmail = data.preferences['kindle.email'];
  if (
    (locale !== 'zh-CN' && locale !== 'en-US') ||
    (playbackRate !== undefined && playbackRate !== null &&
      finiteNumberInRange(playbackRate, 0.5, 3) === null) ||
    (kindleEmail !== undefined && kindleEmail !== null &&
      stringValue(kindleEmail, 320) === null)
  ) {
    return { ok: false, reason: 'INVALID_LIBRARY_PREFERENCES' };
  }
  return {
    ok: true,
    value: {
      view: view === 'grid' || view === 'list' ? view : 'grid',
      sort: isLibrarySort(sort) ? sort : 'recent_read',
      direction: direction === 'asc' || direction === 'desc'
        ? direction
        : 'desc',
    },
  };
}

export function decodeLibraryErrorCode(value: unknown): string | undefined {
  if (!isRecord(value) || !hasOnlyKeys(value, ERROR_ENVELOPE_KEYS) ||
      value.ok !== false || !isRecord(value.error) ||
      !hasOnlyKeys(value.error, ERROR_KEYS) ||
      nonEmptyString(value.error.message, 4_096) === null ||
      (value.error.code !== undefined && value.error.code !== null &&
        nonEmptyString(value.error.code, 128) === null) ||
      (value.error.details !== undefined && value.error.details !== null &&
        !isRecord(value.error.details))) {
    return undefined;
  }
  return nonEmptyString(value.error.code, 128) ?? undefined;
}

import type {
  AudioLocation,
  ComicLocation,
  EpubLocation,
  ErrorEnvelope_ReaderErrorBody_,
  PdfLocation,
  ReaderBookSummary,
  ReaderBootstrapResponse,
  ReaderCapabilities,
  ReaderErrorBody,
  ReaderFileSummary,
  ReaderJsonValue_Output,
  ReaderMediaVersionSummary,
  ReaderUnitSummary,
  ReaderVolumeSummary,
  ReflowableLocation_Output,
} from '../../../../generated/reader-v3';
import type { ValidationResult } from '../../../shared/validation/unknown';
import {
  hasOnlyKeys,
  isRecord,
} from '../../../shared/validation/unknown';

export type ReaderLocationWire =
  | EpubLocation
  | ReflowableLocation_Output
  | ComicLocation
  | PdfLocation
  | AudioLocation;

const ENVELOPE_KEYS = new Set(['ok', 'data']);
const ERROR_ENVELOPE_KEYS = new Set(['ok', 'error']);
const BOOTSTRAP_KEYS = new Set([
  'schemaVersion',
  'userId',
  'readerType',
  'sourceFormat',
  'contentFingerprint',
  'book',
  'mediaVersion',
  'volume',
  'availableVolumes',
  'files',
  'units',
  'fileUrl',
  'capabilities',
  'resumeLocation',
  'resumeFingerprintMismatch',
  'progressPercent',
]);
const BOOK_KEYS = new Set(['id', 'title', 'author', 'coverUrl']);
const MEDIA_VERSION_KEYS = new Set([
  'id',
  'workId',
  'mediaKind',
  'completed',
]);
const VOLUME_KEYS = new Set([
  'id',
  'mediaVersionId',
  'title',
  'volumeIndex',
  'sortOrder',
  'format',
  'readerType',
  'derivedFromVolumeId',
  'pageCount',
  'chapterCount',
  'durationMs',
  'trackCount',
  'progress',
  'lastReadAt',
]);
const FILE_KEYS = new Set([
  'id',
  'kind',
  'mimeType',
  'sizeBytes',
  'durationMs',
  'discNumber',
  'trackNumber',
  'sortOrder',
  'url',
  'codec',
]);
const UNIT_KEYS = new Set([
  'id',
  'index',
  'title',
  'href',
  'fileId',
  'startMs',
  'endMs',
  'durationMs',
  'metadata',
]);
const CAPABILITY_KEYS = new Set([
  'canGoNext',
  'canGoPrevious',
  'canJumpToProgress',
  'canJumpToHref',
  'canJumpToIndex',
  'canZoom',
  'canSelectText',
  'supportsPagination',
  'supportsScrolling',
  'supportsSpreads',
]);
const ERROR_KEYS = new Set(['message', 'code', 'details']);
const EPUB_LOCATION_KEYS = new Set([
  'type',
  'volumeId',
  'cfi',
  'href',
  'spineIndex',
  'progression',
]);
const REFLOWABLE_LOCATION_KEYS = new Set([
  'type',
  'volumeId',
  'format',
  'cfi',
  'href',
  'progression',
  'foliate',
]);
const COMIC_LOCATION_KEYS = new Set(['type', 'volumeId', 'pageIndex']);
const PDF_LOCATION_KEYS = new Set(['type', 'volumeId', 'pageNumber']);
const AUDIO_LOCATION_KEYS = new Set([
  'type',
  'volumeId',
  'fileId',
  'chapterId',
  'positionMs',
]);
const REFLOWABLE_FORMATS = new Set([
  'epub',
  'mobi',
  'azw',
  'azw3',
  'prc',
  'fb2',
  'txt',
]);
const READER_TYPES = new Set(['reflowable', 'comic', 'pdf', 'audio']);
const MEDIA_KINDS = new Set(['EBOOK', 'COMIC', 'AUDIOBOOK']);

function isStringBetween(
  value: unknown,
  minimumLength: number,
  maximumLength = Number.MAX_SAFE_INTEGER,
): value is string {
  return (
    typeof value === 'string' &&
    value.length >= minimumLength &&
    value.length <= maximumLength
  );
}

function isNullableStringBetween(
  value: unknown,
  minimumLength: number,
  maximumLength = Number.MAX_SAFE_INTEGER,
): value is string | null | undefined {
  return (
    value === undefined ||
    value === null ||
    isStringBetween(value, minimumLength, maximumLength)
  );
}

function isFiniteNumberInRange(
  value: unknown,
  minimum: number,
  maximum: number,
): value is number {
  return (
    typeof value === 'number' &&
    Number.isFinite(value) &&
    value >= minimum &&
    value <= maximum
  );
}

function isOptionalFiniteNumberInRange(
  value: unknown,
  minimum: number,
  maximum: number,
): value is number | null | undefined {
  return (
    value === undefined ||
    value === null ||
    isFiniteNumberInRange(value, minimum, maximum)
  );
}

function isSafeIntegerAtLeast(
  value: unknown,
  minimum: number,
): value is number {
  return Number.isSafeInteger(value) && typeof value === 'number' && value >= minimum;
}

function isOptionalSafeIntegerAtLeast(
  value: unknown,
  minimum: number,
): value is number | null | undefined {
  return (
    value === undefined ||
    value === null ||
    isSafeIntegerAtLeast(value, minimum)
  );
}

function isReaderType(value: unknown): boolean {
  return typeof value === 'string' && READER_TYPES.has(value);
}

function isReflowableFormat(value: unknown): boolean {
  return typeof value === 'string' && REFLOWABLE_FORMATS.has(value);
}

function isReaderJsonValue(
  value: unknown,
  depth = 0,
  ancestors: ReadonlySet<object> = new Set(),
): value is ReaderJsonValue_Output {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean'
  ) {
    return true;
  }
  if (typeof value === 'number') return Number.isFinite(value);
  if (depth >= 32 || typeof value !== 'object') return false;
  if (ancestors.has(value)) return false;

  const nextAncestors = new Set(ancestors);
  nextAncestors.add(value);
  if (Array.isArray(value)) {
    return value.every((entry) =>
      isReaderJsonValue(entry, depth + 1, nextAncestors),
    );
  }
  if (!isRecord(value)) return false;
  return Object.values(value).every((entry) =>
    isReaderJsonValue(entry, depth + 1, nextAncestors),
  );
}

function isReaderJsonObject(
  value: unknown,
): value is Readonly<Record<string, ReaderJsonValue_Output>> {
  return isRecord(value) && Object.values(value).every((entry) => isReaderJsonValue(entry));
}

function isEpubLocation(value: unknown): value is EpubLocation {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, EPUB_LOCATION_KEYS) ||
    value.type !== 'epub' ||
    !isNullableStringBetween(value.volumeId, 1) ||
    !isNullableStringBetween(value.cfi, 1, 4096) ||
    !isNullableStringBetween(value.href, 1, 2048) ||
    !isOptionalSafeIntegerAtLeast(value.spineIndex, 0) ||
    !isOptionalFiniteNumberInRange(value.progression, 0, 1)
  ) {
    return false;
  }
  return (
    value.cfi !== undefined && value.cfi !== null ||
    value.href !== undefined && value.href !== null ||
    value.spineIndex !== undefined && value.spineIndex !== null ||
    value.progression !== undefined && value.progression !== null
  );
}

function isReflowableLocation(
  value: unknown,
): value is ReflowableLocation_Output {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, REFLOWABLE_LOCATION_KEYS) ||
    value.type !== 'reflowable' ||
    !isNullableStringBetween(value.volumeId, 1) ||
    !isReflowableFormat(value.format) ||
    !isNullableStringBetween(value.cfi, 1, 4096) ||
    !isNullableStringBetween(value.href, 1, 2048) ||
    !isOptionalFiniteNumberInRange(value.progression, 0, 1) ||
    !(
      value.foliate === undefined ||
      value.foliate === null ||
      isReaderJsonObject(value.foliate)
    )
  ) {
    return false;
  }
  return (
    value.cfi !== undefined && value.cfi !== null ||
    value.href !== undefined && value.href !== null ||
    value.progression !== undefined && value.progression !== null
  );
}

function isComicLocation(value: unknown): value is ComicLocation {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, COMIC_LOCATION_KEYS) &&
    value.type === 'comic' &&
    isNullableStringBetween(value.volumeId, 1) &&
    isSafeIntegerAtLeast(value.pageIndex, 1)
  );
}

function isPdfLocation(value: unknown): value is PdfLocation {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, PDF_LOCATION_KEYS) &&
    value.type === 'pdf' &&
    isNullableStringBetween(value.volumeId, 1) &&
    isSafeIntegerAtLeast(value.pageNumber, 1)
  );
}

function isAudioLocation(value: unknown): value is AudioLocation {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, AUDIO_LOCATION_KEYS) &&
    value.type === 'audio' &&
    isNullableStringBetween(value.volumeId, 1) &&
    isStringBetween(value.fileId, 1, 191) &&
    isNullableStringBetween(value.chapterId, 0, 191) &&
    isSafeIntegerAtLeast(value.positionMs, 0)
  );
}

function isReaderLocation(value: unknown): value is ReaderLocationWire {
  if (!isRecord(value)) return false;
  switch (value.type) {
    case 'epub':
      return isEpubLocation(value);
    case 'reflowable':
      return isReflowableLocation(value);
    case 'comic':
      return isComicLocation(value);
    case 'pdf':
      return isPdfLocation(value);
    case 'audio':
      return isAudioLocation(value);
    default:
      return false;
  }
}

function isBook(value: unknown): value is ReaderBookSummary {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, BOOK_KEYS) &&
    typeof value.id === 'string' &&
    typeof value.title === 'string' &&
    isNullableStringBetween(value.author, 0) &&
    isNullableStringBetween(value.coverUrl, 0)
  );
}

function isMediaVersion(
  value: unknown,
): value is ReaderMediaVersionSummary {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, MEDIA_VERSION_KEYS) &&
    typeof value.id === 'string' &&
    typeof value.workId === 'string' &&
    typeof value.mediaKind === 'string' &&
    MEDIA_KINDS.has(value.mediaKind) &&
    typeof value.completed === 'boolean'
  );
}

function isVolume(value: unknown): value is ReaderVolumeSummary {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, VOLUME_KEYS) &&
    typeof value.id === 'string' &&
    typeof value.mediaVersionId === 'string' &&
    typeof value.title === 'string' &&
    isOptionalFiniteNumberInRange(
      value.volumeIndex,
      -Number.MAX_VALUE,
      Number.MAX_VALUE,
    ) &&
    isSafeIntegerAtLeast(value.sortOrder, -Number.MAX_SAFE_INTEGER) &&
    typeof value.format === 'string' &&
    isReaderType(value.readerType) &&
    isNullableStringBetween(value.derivedFromVolumeId, 1) &&
    isOptionalSafeIntegerAtLeast(value.pageCount, -Number.MAX_SAFE_INTEGER) &&
    isOptionalSafeIntegerAtLeast(value.chapterCount, -Number.MAX_SAFE_INTEGER) &&
    isOptionalSafeIntegerAtLeast(value.durationMs, -Number.MAX_SAFE_INTEGER) &&
    isOptionalSafeIntegerAtLeast(value.trackCount, -Number.MAX_SAFE_INTEGER) &&
    isFiniteNumberInRange(value.progress, 0, 100) &&
    isNullableStringBetween(value.lastReadAt, 1)
  );
}

function isReaderFile(value: unknown): value is ReaderFileSummary {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, FILE_KEYS) &&
    typeof value.id === 'string' &&
    typeof value.kind === 'string' &&
    typeof value.mimeType === 'string' &&
    isSafeIntegerAtLeast(value.sizeBytes, 0) &&
    isOptionalSafeIntegerAtLeast(value.durationMs, 0) &&
    isOptionalSafeIntegerAtLeast(value.discNumber, -Number.MAX_SAFE_INTEGER) &&
    isOptionalSafeIntegerAtLeast(value.trackNumber, -Number.MAX_SAFE_INTEGER) &&
    isSafeIntegerAtLeast(value.sortOrder, -Number.MAX_SAFE_INTEGER) &&
    typeof value.url === 'string' &&
    isNullableStringBetween(value.codec, 0)
  );
}

function isReaderUnit(value: unknown): value is ReaderUnitSummary {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, UNIT_KEYS) &&
    typeof value.id === 'string' &&
    isSafeIntegerAtLeast(value.index, -Number.MAX_SAFE_INTEGER) &&
    typeof value.title === 'string' &&
    isNullableStringBetween(value.href, 0) &&
    isNullableStringBetween(value.fileId, 0) &&
    isOptionalSafeIntegerAtLeast(value.startMs, 0) &&
    isOptionalSafeIntegerAtLeast(value.endMs, 0) &&
    isOptionalSafeIntegerAtLeast(value.durationMs, 0) &&
    (value.metadata === undefined || isReaderJsonObject(value.metadata))
  );
}

function isCapabilities(value: unknown): value is ReaderCapabilities {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, CAPABILITY_KEYS) &&
    [...CAPABILITY_KEYS].every((key) => typeof value[key] === 'boolean')
  );
}

function isReaderBootstrapResponse(
  value: unknown,
): value is ReaderBootstrapResponse {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ENVELOPE_KEYS) ||
    (value.ok !== undefined && value.ok !== true) ||
    !isRecord(value.data) ||
    !hasOnlyKeys(value.data, BOOTSTRAP_KEYS)
  ) {
    return false;
  }
  const data = value.data;
  const shapeIsValid = (
    (data.schemaVersion === undefined || data.schemaVersion === 3) &&
    typeof data.userId === 'string' &&
    isReaderType(data.readerType) &&
    (data.sourceFormat === undefined ||
      data.sourceFormat === null ||
      isReflowableFormat(data.sourceFormat)) &&
    typeof data.contentFingerprint === 'string' &&
    isBook(data.book) &&
    isMediaVersion(data.mediaVersion) &&
    isVolume(data.volume) &&
    Array.isArray(data.availableVolumes) &&
    data.availableVolumes.every(isVolume) &&
    Array.isArray(data.files) &&
    data.files.every(isReaderFile) &&
    Array.isArray(data.units) &&
    data.units.every(isReaderUnit) &&
    typeof data.fileUrl === 'string' &&
    isCapabilities(data.capabilities) &&
    (data.resumeLocation === undefined ||
      data.resumeLocation === null ||
      isReaderLocation(data.resumeLocation)) &&
    (data.resumeFingerprintMismatch === undefined ||
      typeof data.resumeFingerprintMismatch === 'boolean') &&
    (data.progressPercent === undefined ||
      isFiniteNumberInRange(data.progressPercent, 0, 100))
  );
  if (!shapeIsValid) return false;

  const book = data.book;
  const mediaVersion = data.mediaVersion;
  const volume = data.volume;
  const availableVolumes = data.availableVolumes;
  return (
    isBook(book) &&
    isMediaVersion(mediaVersion) &&
    isVolume(volume) &&
    Array.isArray(availableVolumes) &&
    availableVolumes.every(isVolume) &&
    book.id === mediaVersion.workId &&
    mediaVersion.id === volume.mediaVersionId &&
    data.readerType === volume.readerType &&
    availableVolumes.every(
      (availableVolume) =>
        availableVolume.mediaVersionId === mediaVersion.id,
    )
  );
}

function isReaderErrorBody(value: unknown): value is ReaderErrorBody {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ERROR_KEYS) &&
    typeof value.message === 'string' &&
    isNullableStringBetween(value.code, 0) &&
    (value.details === undefined ||
      value.details === null ||
      isReaderJsonObject(value.details))
  );
}

function isReaderErrorResponse(
  value: unknown,
): value is ErrorEnvelope_ReaderErrorBody_ {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ERROR_ENVELOPE_KEYS) &&
    (value.ok === undefined || value.ok === false) &&
    isReaderErrorBody(value.error)
  );
}

export function decodeReaderLocationWire(
  value: unknown,
): ValidationResult<ReaderLocationWire> {
  return isReaderLocation(value)
    ? { ok: true, value }
    : { ok: false, reason: 'INVALID_READER_V3_LOCATION' };
}

export function decodeReaderBootstrapResponse(
  value: unknown,
): ValidationResult<ReaderBootstrapResponse> {
  return isReaderBootstrapResponse(value)
    ? { ok: true, value }
    : { ok: false, reason: 'INVALID_READER_V3_BOOTSTRAP' };
}

export function decodeReaderErrorBody(
  value: unknown,
): ValidationResult<ReaderErrorBody> {
  return isReaderErrorBody(value)
    ? { ok: true, value }
    : { ok: false, reason: 'INVALID_READER_V3_ERROR' };
}

export function decodeReaderErrorResponse(
  value: unknown,
): ValidationResult<ErrorEnvelope_ReaderErrorBody_> {
  return isReaderErrorResponse(value)
    ? { ok: true, value }
    : { ok: false, reason: 'INVALID_READER_V3_ERROR_ENVELOPE' };
}

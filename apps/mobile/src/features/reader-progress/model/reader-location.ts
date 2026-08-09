import type {
  ComicLocation,
  FoliateProgressSnapshot,
  PdfLocation,
  ReflowableFormat,
  ReflowableLocation,
} from '@shuku/reader-core';

import {
  type ValidationResult,
  finiteNumberInRange,
  hasOnlyKeys,
  isRecord,
  nonEmptyString,
  nonNegativeSafeInteger,
} from '../../../shared/validation/unknown';

const REFLOWABLE_KEYS = new Set([
  'kind',
  'format',
  'cfi',
  'href',
  'progression',
  'foliate',
]);
const REFLOWABLE_FORMATS: ReadonlySet<string> = new Set([
  'epub',
  'mobi',
  'azw',
  'azw3',
  'prc',
  'fb2',
  'txt',
]);
const COMIC_KEYS = new Set(['kind', 'volumeId', 'pageIndex']);
const PDF_KEYS = new Set(['kind', 'pageNumber']);
const FOLIATE_KEYS = new Set([
  'continuous',
  'toc',
  'navigationFingerprint',
  'section',
  'location',
  'remainingSeconds',
]);
const FOLIATE_CONTINUOUS_KEYS = new Set(['sectionFraction']);
const FOLIATE_TOC_KEYS = new Set([
  'index',
  'title',
  'href',
  'navigationKey',
]);
const FOLIATE_SECTION_KEYS = new Set(['current', 'total']);
const FOLIATE_LOCATION_KEYS = new Set(['current', 'next', 'total']);
const FOLIATE_REMAINING_SECONDS_KEYS = new Set(['section', 'total']);

const MAXIMUM_CFI_LENGTH = 4_096;
const MAXIMUM_HREF_LENGTH = 2_048;
const MAXIMUM_FOLIATE_TITLE_LENGTH = 4_096;
const MAXIMUM_NAVIGATION_KEY_LENGTH = 4_096;
const MAXIMUM_FINGERPRINT_LENGTH = 191;

export type ReaderProgressLocation =
  | ReflowableLocation
  | ComicLocation
  | PdfLocation;

type OptionalDecoded<Value> =
  | Readonly<{ ok: true; value: Value | undefined }>
  | Readonly<{ ok: false }>;

function optionalString(
  record: Readonly<Record<string, unknown>>,
  key: string,
  maximumLength: number,
): OptionalDecoded<string> {
  if (!(key in record)) {
    return { ok: true, value: undefined };
  }
  const decoded = nonEmptyString(record[key], maximumLength);
  return decoded === null
    ? { ok: false }
    : { ok: true, value: decoded };
}

function optionalUnitNumber(
  record: Readonly<Record<string, unknown>>,
  key: string,
): OptionalDecoded<number> {
  if (!(key in record)) {
    return { ok: true, value: undefined };
  }
  const decoded = finiteNumberInRange(record[key], 0, 1);
  return decoded === null
    ? { ok: false }
    : { ok: true, value: decoded };
}

function isReflowableFormat(value: unknown): value is ReflowableFormat {
  return typeof value === 'string' && REFLOWABLE_FORMATS.has(value);
}

function decodeFoliateContinuous(
  value: unknown,
): FoliateProgressSnapshot['continuous'] | null {
  if (!isRecord(value) || !hasOnlyKeys(value, FOLIATE_CONTINUOUS_KEYS)) {
    return null;
  }
  const sectionFraction = finiteNumberInRange(value.sectionFraction, 0, 1);
  return sectionFraction === null ? null : { sectionFraction };
}

function decodeFoliateToc(
  value: unknown,
): FoliateProgressSnapshot['toc'] | null {
  if (!isRecord(value) || !hasOnlyKeys(value, FOLIATE_TOC_KEYS)) {
    return null;
  }
  const index = nonNegativeSafeInteger(value.index);
  const title = nonEmptyString(value.title, MAXIMUM_FOLIATE_TITLE_LENGTH);
  const href = optionalString(value, 'href', MAXIMUM_HREF_LENGTH);
  const navigationKey = optionalString(
    value,
    'navigationKey',
    MAXIMUM_NAVIGATION_KEY_LENGTH,
  );
  if (index === null || title === null || !href.ok || !navigationKey.ok) {
    return null;
  }
  return {
    index,
    title,
    ...(href.value === undefined ? {} : { href: href.value }),
    ...(navigationKey.value === undefined
      ? {}
      : { navigationKey: navigationKey.value }),
  };
}

function decodeFoliateSection(
  value: unknown,
): FoliateProgressSnapshot['section'] | null {
  if (!isRecord(value) || !hasOnlyKeys(value, FOLIATE_SECTION_KEYS)) {
    return null;
  }
  const current = nonNegativeSafeInteger(value.current);
  const total = nonNegativeSafeInteger(value.total);
  if (current === null || total === null || total < 1 || current >= total) {
    return null;
  }
  return { current, total };
}

function decodeFoliateLocationProgress(
  value: unknown,
): FoliateProgressSnapshot['location'] | null {
  if (!isRecord(value) || !hasOnlyKeys(value, FOLIATE_LOCATION_KEYS)) {
    return null;
  }
  const current = nonNegativeSafeInteger(value.current);
  const next = nonNegativeSafeInteger(value.next);
  const total = nonNegativeSafeInteger(value.total);
  if (
    current === null ||
    next === null ||
    total === null ||
    total < 1 ||
    current >= total ||
    next < current ||
    next > total
  ) {
    return null;
  }
  return { current, next, total };
}

function decodeFoliateRemainingSeconds(
  value: unknown,
): FoliateProgressSnapshot['remainingSeconds'] | null {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, FOLIATE_REMAINING_SECONDS_KEYS)
  ) {
    return null;
  }
  const section = finiteNumberInRange(value.section, 0, Number.MAX_VALUE);
  const total = finiteNumberInRange(value.total, 0, Number.MAX_VALUE);
  return section === null || total === null ? null : { section, total };
}

function decodeFoliateProgress(
  value: unknown,
): FoliateProgressSnapshot | null {
  if (!isRecord(value) || !hasOnlyKeys(value, FOLIATE_KEYS)) {
    return null;
  }

  const continuous =
    'continuous' in value
      ? decodeFoliateContinuous(value.continuous)
      : undefined;
  const toc = 'toc' in value ? decodeFoliateToc(value.toc) : undefined;
  const navigationFingerprint = optionalString(
    value,
    'navigationFingerprint',
    MAXIMUM_FINGERPRINT_LENGTH,
  );
  const section =
    'section' in value ? decodeFoliateSection(value.section) : undefined;
  const location =
    'location' in value
      ? decodeFoliateLocationProgress(value.location)
      : undefined;
  const remainingSeconds =
    'remainingSeconds' in value
      ? decodeFoliateRemainingSeconds(value.remainingSeconds)
      : undefined;
  if (
    continuous === null ||
    toc === null ||
    !navigationFingerprint.ok ||
    section === null ||
    location === null ||
    remainingSeconds === null
  ) {
    return null;
  }

  return {
    ...(continuous === undefined ? {} : { continuous }),
    ...(toc === undefined ? {} : { toc }),
    ...(navigationFingerprint.value === undefined
      ? {}
      : { navigationFingerprint: navigationFingerprint.value }),
    ...(section === undefined ? {} : { section }),
    ...(location === undefined ? {} : { location }),
    ...(remainingSeconds === undefined ? {} : { remainingSeconds }),
  };
}

function decodeReflowableLocation(
  value: Readonly<Record<string, unknown>>,
): ValidationResult<ReaderProgressLocation> {
  if (
    !hasOnlyKeys(value, REFLOWABLE_KEYS) ||
    !isReflowableFormat(value.format)
  ) {
    return { ok: false, reason: 'INVALID_REFLOWABLE_LOCATION' };
  }
  const cfi = optionalString(value, 'cfi', MAXIMUM_CFI_LENGTH);
  const href = optionalString(value, 'href', MAXIMUM_HREF_LENGTH);
  const progression = optionalUnitNumber(value, 'progression');
  const foliate =
    'foliate' in value ? decodeFoliateProgress(value.foliate) : undefined;
  if (
    !cfi.ok ||
    !href.ok ||
    !progression.ok ||
    foliate === null ||
    (cfi.value === undefined &&
      href.value === undefined &&
      progression.value === undefined)
  ) {
    return { ok: false, reason: 'INVALID_REFLOWABLE_LOCATION' };
  }
  const location: ReflowableLocation = {
    kind: 'reflowable',
    format: value.format,
    ...(cfi.value === undefined ? {} : { cfi: cfi.value }),
    ...(href.value === undefined ? {} : { href: href.value }),
    ...(progression.value === undefined
      ? {}
      : { progression: progression.value }),
    ...(foliate === undefined ? {} : { foliate }),
  };
  return { ok: true, value: location };
}

export function decodeReaderLocation(
  value: unknown,
): ValidationResult<ReaderProgressLocation> {
  if (!isRecord(value)) {
    return { ok: false, reason: 'INVALID_READER_LOCATION' };
  }
  if (value.kind === 'reflowable') {
    return decodeReflowableLocation(value);
  }
  if (value.kind === 'comic') {
    const volumeId = nonEmptyString(value.volumeId, 191);
    const pageIndex = nonNegativeSafeInteger(value.pageIndex);
    if (
      !hasOnlyKeys(value, COMIC_KEYS) ||
      volumeId === null ||
      pageIndex === null ||
      pageIndex < 1
    ) {
      return { ok: false, reason: 'INVALID_COMIC_LOCATION' };
    }
    return {
      ok: true,
      value: { kind: 'comic', volumeId, pageIndex },
    };
  }
  if (value.kind === 'pdf') {
    const pageNumber = nonNegativeSafeInteger(value.pageNumber);
    if (
      !hasOnlyKeys(value, PDF_KEYS) ||
      pageNumber === null ||
      pageNumber < 1
    ) {
      return { ok: false, reason: 'INVALID_PDF_LOCATION' };
    }
    return { ok: true, value: { kind: 'pdf', pageNumber } };
  }
  return { ok: false, reason: 'UNSUPPORTED_READER_LOCATION' };
}

export function encodeReaderLocation(
  location: ReaderProgressLocation,
): unknown {
  if (location.kind === 'reflowable') {
    return {
      kind: location.kind,
      format: location.format,
      ...(location.cfi === undefined ? {} : { cfi: location.cfi }),
      ...(location.href === undefined ? {} : { href: location.href }),
      ...(location.progression === undefined
        ? {}
        : { progression: location.progression }),
      ...(location.foliate === undefined
        ? {}
        : { foliate: location.foliate }),
    };
  }
  if (location.kind === 'comic') {
    return {
      kind: location.kind,
      volumeId: location.volumeId,
      pageIndex: location.pageIndex,
    };
  }
  return {
    kind: location.kind,
    pageNumber: location.pageNumber,
  };
}

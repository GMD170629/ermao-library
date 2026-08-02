import type {
  ReflowableFormat,
  ReflowableLocation,
  ReaderLocation,
} from '@shuku/reader-core';

import {
  type ValidationResult,
  finiteNumberInRange,
  hasOnlyKeys,
  isRecord,
  nonEmptyString,
  nonNegativeSafeInteger,
} from '../../../shared/validation/unknown';

const EPUB_KEYS = new Set([
  'kind',
  'cfi',
  'href',
  'spineIndex',
  'progression',
]);
const REFLOWABLE_KEYS = new Set(['kind', 'format', 'cfi', 'href', 'progression']);
const REFLOWABLE_FORMATS = new Set<ReflowableFormat>([
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

function optionalNonNegativeInteger(
  record: Readonly<Record<string, unknown>>,
  key: string,
): OptionalDecoded<number> {
  if (!(key in record)) {
    return { ok: true, value: undefined };
  }
  const decoded = nonNegativeSafeInteger(record[key]);
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

function decodeEpubLocation(
  value: Readonly<Record<string, unknown>>,
): ValidationResult<ReaderLocation> {
  if (!hasOnlyKeys(value, EPUB_KEYS)) {
    return { ok: false, reason: 'INVALID_EPUB_LOCATION' };
  }

  const cfi = optionalString(value, 'cfi', 4_096);
  const href = optionalString(value, 'href', 2_048);
  const spineIndex = optionalNonNegativeInteger(value, 'spineIndex');
  const progression = optionalUnitNumber(value, 'progression');
  if (
    !cfi.ok ||
    !href.ok ||
    !spineIndex.ok ||
    !progression.ok ||
    (cfi.value === undefined &&
      href.value === undefined &&
      progression.value === undefined)
  ) {
    return { ok: false, reason: 'INVALID_EPUB_LOCATION' };
  }

  const location: ReflowableLocation = {
    kind: 'reflowable',
    format: 'epub',
    ...(cfi.value === undefined ? {} : { cfi: cfi.value }),
    ...(href.value === undefined ? {} : { href: href.value }),
    ...(progression.value === undefined
      ? {}
      : { progression: progression.value }),
  };
  return { ok: true, value: location };
}

function decodeReflowableLocation(
  value: Readonly<Record<string, unknown>>,
): ValidationResult<ReaderLocation> {
  if (
    !hasOnlyKeys(value, REFLOWABLE_KEYS) ||
    typeof value.format !== 'string' ||
    !REFLOWABLE_FORMATS.has(value.format as ReflowableFormat)
  ) {
    return { ok: false, reason: 'INVALID_REFLOWABLE_LOCATION' };
  }
  const cfi = optionalString(value, 'cfi', 4_096);
  const href = optionalString(value, 'href', 2_048);
  const progression = optionalUnitNumber(value, 'progression');
  if (
    !cfi.ok ||
    !href.ok ||
    !progression.ok ||
    (cfi.value === undefined &&
      href.value === undefined &&
      progression.value === undefined)
  ) {
    return { ok: false, reason: 'INVALID_REFLOWABLE_LOCATION' };
  }
  const location: ReflowableLocation = {
    kind: 'reflowable',
    format: value.format as ReflowableFormat,
    ...(cfi.value === undefined ? {} : { cfi: cfi.value }),
    ...(href.value === undefined ? {} : { href: href.value }),
    ...(progression.value === undefined ? {} : { progression: progression.value }),
  };
  return { ok: true, value: location };
}

export function decodeReaderLocation(
  value: unknown,
): ValidationResult<ReaderLocation> {
  if (!isRecord(value)) {
    return { ok: false, reason: 'INVALID_READER_LOCATION' };
  }
  if (value.kind === 'epub') {
    return decodeEpubLocation(value);
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

export function encodeReaderLocation(location: ReaderLocation): unknown {
  if (location.kind === 'reflowable') {
    return {
      kind: location.kind,
      format: location.format,
      ...(location.cfi === undefined ? {} : { cfi: location.cfi }),
      ...(location.href === undefined ? {} : { href: location.href }),
      ...(location.progression === undefined ? {} : { progression: location.progression }),
    };
  }
  if (location.kind === 'epub') {
    return {
      kind: location.kind,
      ...(location.cfi === undefined ? {} : { cfi: location.cfi }),
      ...(location.href === undefined ? {} : { href: location.href }),
      ...(location.spineIndex === undefined
        ? {}
        : { spineIndex: location.spineIndex }),
      ...(location.progression === undefined
        ? {}
        : { progression: location.progression }),
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

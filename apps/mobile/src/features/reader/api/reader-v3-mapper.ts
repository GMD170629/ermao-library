import type {
  FoliateProgressSnapshot,
  ReaderLocation,
  ReaderNavigationEntry,
  ReaderSource,
} from '@shuku/reader-core';

import type {
  ReaderBootstrapData,
  ReaderJsonValue_Input,
  ReaderProgressPut,
} from '../../../../generated/reader-v3';
import type { ValidationResult } from '../../../shared/validation/unknown';
import {
  hasOnlyKeys,
  isRecord,
} from '../../../shared/validation/unknown';
import {
  decodeReaderLocationWire,
  type ReaderLocationWire,
} from './reader-v3-wire';

const FOLIATE_KEYS = new Set([
  'continuous',
  'toc',
  'navigationFingerprint',
  'section',
  'location',
  'remainingSeconds',
]);
const CONTINUOUS_KEYS = new Set(['sectionFraction']);
const TOC_KEYS = new Set([
  'index',
  'title',
  'href',
  'navigationKey',
]);
const SECTION_KEYS = new Set(['current', 'total']);
const LOCATION_KEYS = new Set(['current', 'next', 'total']);
const REMAINING_SECONDS_KEYS = new Set(['section', 'total']);
const MAXIMUM_HREF_LENGTH = 2_048;
const MAXIMUM_FOLIATE_TITLE_LENGTH = 4_096;
const MAXIMUM_NAVIGATION_KEY_LENGTH = 4_096;
const MAXIMUM_FINGERPRINT_LENGTH = 191;

export type CreateReaderProgressPutInput = Readonly<{
  volumeId: string;
  mutationId: string;
  clientId: string;
  clientSequence: number;
  contentFingerprint: string;
  location: ReaderLocation;
  percent: number;
}>;

function isFiniteNumberAtLeast(value: unknown, minimum: number): value is number {
  return (
    typeof value === 'number' &&
    Number.isFinite(value) &&
    value >= minimum
  );
}

function isSafeIntegerAtLeast(value: unknown, minimum: number): value is number {
  return Number.isSafeInteger(value) && typeof value === 'number' && value >= minimum;
}

function isBoundedNonEmptyString(
  value: unknown,
  maximumLength: number,
): value is string {
  return (
    typeof value === 'string' &&
    value.trim().length > 0 &&
    value.trim().length <= maximumLength
  );
}

function isOptionalBoundedNonEmptyString(
  value: unknown,
  maximumLength: number,
): value is string | undefined {
  return value === undefined || isBoundedNonEmptyString(value, maximumLength);
}

function isFoliateProgressSnapshot(
  value: unknown,
): value is FoliateProgressSnapshot {
  if (!isRecord(value) || !hasOnlyKeys(value, FOLIATE_KEYS)) return false;

  const continuousValid =
    value.continuous === undefined ||
    (isRecord(value.continuous) &&
      hasOnlyKeys(value.continuous, CONTINUOUS_KEYS) &&
      Object.hasOwn(value.continuous, 'sectionFraction') &&
      isFiniteNumberAtLeast(value.continuous.sectionFraction, 0) &&
      value.continuous.sectionFraction <= 1);
  const tocValid =
    value.toc === undefined ||
    (isRecord(value.toc) &&
      hasOnlyKeys(value.toc, TOC_KEYS) &&
      isSafeIntegerAtLeast(value.toc.index, 0) &&
      isBoundedNonEmptyString(
        value.toc.title,
        MAXIMUM_FOLIATE_TITLE_LENGTH,
      ) &&
      isOptionalBoundedNonEmptyString(value.toc.href, MAXIMUM_HREF_LENGTH) &&
      isOptionalBoundedNonEmptyString(
        value.toc.navigationKey,
        MAXIMUM_NAVIGATION_KEY_LENGTH,
      ));
  const sectionValid =
    value.section === undefined ||
    (isRecord(value.section) &&
      hasOnlyKeys(value.section, SECTION_KEYS) &&
      isSafeIntegerAtLeast(value.section.current, 0) &&
      isSafeIntegerAtLeast(value.section.total, 1) &&
      value.section.current < value.section.total);
  const locationValid =
    value.location === undefined ||
    (isRecord(value.location) &&
      hasOnlyKeys(value.location, LOCATION_KEYS) &&
      isSafeIntegerAtLeast(value.location.current, 0) &&
      isSafeIntegerAtLeast(value.location.next, 0) &&
      isSafeIntegerAtLeast(value.location.total, 1) &&
      value.location.current < value.location.total &&
      value.location.next >= value.location.current &&
      value.location.next <= value.location.total);
  const remainingSecondsValid =
    value.remainingSeconds === undefined ||
    (isRecord(value.remainingSeconds) &&
      hasOnlyKeys(value.remainingSeconds, REMAINING_SECONDS_KEYS) &&
      isFiniteNumberAtLeast(value.remainingSeconds.section, 0) &&
      isFiniteNumberAtLeast(value.remainingSeconds.total, 0));

  return (
    continuousValid &&
    tocValid &&
    isOptionalBoundedNonEmptyString(
      value.navigationFingerprint,
      MAXIMUM_FINGERPRINT_LENGTH,
    ) &&
    sectionValid &&
    locationValid &&
    remainingSecondsValid
  );
}

function matchingVolume(
  wireVolumeId: string | null | undefined,
  volumeId: string,
): boolean {
  return wireVolumeId === undefined || wireVolumeId === null || wireVolumeId === volumeId;
}

export function mapReaderLocationFromWire(
  wireLocation: ReaderLocationWire,
  volumeId: string,
): ValidationResult<ReaderLocation> {
  if (volumeId.length === 0 || !matchingVolume(wireLocation.volumeId, volumeId)) {
    return { ok: false, reason: 'READER_V3_LOCATION_VOLUME_MISMATCH' };
  }

  switch (wireLocation.type) {
    case 'epub': {
      const location: ReaderLocation = { kind: 'epub' };
      if (wireLocation.cfi !== undefined && wireLocation.cfi !== null) {
        location.cfi = wireLocation.cfi;
      }
      if (wireLocation.href !== undefined && wireLocation.href !== null) {
        location.href = wireLocation.href;
      }
      if (
        wireLocation.spineIndex !== undefined &&
        wireLocation.spineIndex !== null
      ) {
        location.spineIndex = wireLocation.spineIndex;
      }
      if (
        wireLocation.progression !== undefined &&
        wireLocation.progression !== null
      ) {
        location.progression = wireLocation.progression;
      }
      return { ok: true, value: location };
    }
    case 'reflowable': {
      const location: ReaderLocation = {
        kind: 'reflowable',
        format: wireLocation.format,
      };
      if (wireLocation.cfi !== undefined && wireLocation.cfi !== null) {
        location.cfi = wireLocation.cfi;
      }
      if (wireLocation.href !== undefined && wireLocation.href !== null) {
        location.href = wireLocation.href;
      }
      if (
        wireLocation.progression !== undefined &&
        wireLocation.progression !== null
      ) {
        location.progression = wireLocation.progression;
      }
      if (wireLocation.foliate !== undefined && wireLocation.foliate !== null) {
        if (!isFoliateProgressSnapshot(wireLocation.foliate)) {
          return { ok: false, reason: 'INVALID_FOLIATE_PROGRESS_SNAPSHOT' };
        }
        location.foliate = wireLocation.foliate;
      }
      return { ok: true, value: location };
    }
    case 'comic':
      return {
        ok: true,
        value: {
          kind: 'comic',
          volumeId,
          pageIndex: wireLocation.pageIndex,
        },
      };
    case 'pdf':
      return {
        ok: true,
        value: { kind: 'pdf', pageNumber: wireLocation.pageNumber },
      };
    case 'audio':
      return { ok: false, reason: 'READER_CORE_AUDIO_NOT_SUPPORTED' };
  }
}

function encodeFoliateProgressSnapshot(
  snapshot: FoliateProgressSnapshot,
): Readonly<Record<string, ReaderJsonValue_Input>> {
  const result: Record<string, ReaderJsonValue_Input> = {};
  if (snapshot.continuous !== undefined) {
    result.continuous = {
      sectionFraction: snapshot.continuous.sectionFraction,
    };
  }
  if (snapshot.toc !== undefined) {
    result.toc = {
      index: snapshot.toc.index,
      title: snapshot.toc.title,
      ...(snapshot.toc.href === undefined ? {} : { href: snapshot.toc.href }),
      ...(snapshot.toc.navigationKey === undefined
        ? {}
        : { navigationKey: snapshot.toc.navigationKey }),
    };
  }
  if (snapshot.navigationFingerprint !== undefined) {
    result.navigationFingerprint = snapshot.navigationFingerprint;
  }
  if (snapshot.section !== undefined) {
    result.section = {
      current: snapshot.section.current,
      total: snapshot.section.total,
    };
  }
  if (snapshot.location !== undefined) {
    result.location = {
      current: snapshot.location.current,
      next: snapshot.location.next,
      total: snapshot.location.total,
    };
  }
  if (snapshot.remainingSeconds !== undefined) {
    result.remainingSeconds = {
      section: snapshot.remainingSeconds.section,
      total: snapshot.remainingSeconds.total,
    };
  }
  return result;
}

export function mapReaderLocationToWire(
  location: ReaderLocation,
  volumeId: string,
): ValidationResult<ReaderProgressPut['location']> {
  if (volumeId.length === 0) {
    return { ok: false, reason: 'INVALID_READER_V3_VOLUME_ID' };
  }

  let rawLocation: unknown;
  switch (location.kind) {
    case 'epub':
      rawLocation = {
        type: 'epub',
        volumeId,
        ...(location.cfi === undefined ? {} : { cfi: location.cfi }),
        ...(location.href === undefined ? {} : { href: location.href }),
        ...(location.spineIndex === undefined
          ? {}
          : { spineIndex: location.spineIndex }),
        ...(location.progression === undefined
          ? {}
          : { progression: location.progression }),
      };
      break;
    case 'reflowable':
      if (
        location.foliate !== undefined &&
        !isFoliateProgressSnapshot(location.foliate)
      ) {
        return { ok: false, reason: 'INVALID_FOLIATE_PROGRESS_SNAPSHOT' };
      }
      rawLocation = {
        type: 'reflowable',
        volumeId,
        format: location.format,
        ...(location.cfi === undefined ? {} : { cfi: location.cfi }),
        ...(location.href === undefined ? {} : { href: location.href }),
        ...(location.progression === undefined
          ? {}
          : { progression: location.progression }),
        ...(location.foliate === undefined
          ? {}
          : { foliate: encodeFoliateProgressSnapshot(location.foliate) }),
      };
      break;
    case 'comic':
      if (location.volumeId !== volumeId) {
        return { ok: false, reason: 'READER_V3_LOCATION_VOLUME_MISMATCH' };
      }
      rawLocation = {
        type: 'comic',
        volumeId,
        pageIndex: location.pageIndex,
      };
      break;
    case 'pdf':
      rawLocation = {
        type: 'pdf',
        volumeId,
        pageNumber: location.pageNumber,
      };
      break;
  }

  const decoded = decodeReaderLocationWire(rawLocation);
  return decoded.ok
    ? { ok: true, value: decoded.value }
    : { ok: false, reason: decoded.reason };
}

export function createReaderProgressPut(
  input: CreateReaderProgressPutInput,
): ValidationResult<ReaderProgressPut> {
  if (
    input.mutationId.length === 0 ||
    input.mutationId.length > 191 ||
    input.clientId.length === 0 ||
    input.clientId.length > 191 ||
    !isSafeIntegerAtLeast(input.clientSequence, 0) ||
    input.contentFingerprint.length === 0 ||
    input.contentFingerprint.length > 191 ||
    !isFiniteNumberAtLeast(input.percent, 0) ||
    input.percent > 100
  ) {
    return { ok: false, reason: 'INVALID_READER_V3_PROGRESS_INPUT' };
  }

  const location = mapReaderLocationToWire(input.location, input.volumeId);
  if (!location.ok) return location;

  return {
    ok: true,
    value: {
      schemaVersion: 3,
      mutationId: input.mutationId,
      clientId: input.clientId,
      clientSequence: input.clientSequence,
      contentFingerprint: input.contentFingerprint,
      location: location.value,
      percent: input.percent,
    },
  };
}

function resolveContentUrl(
  serverBaseUrl: string,
  fileUrl: string,
): ValidationResult<string> {
  try {
    const base = new URL(serverBaseUrl);
    if (
      (base.protocol !== 'http:' && base.protocol !== 'https:') ||
      base.username.length > 0 ||
      base.password.length > 0
    ) {
      return { ok: false, reason: 'INVALID_READER_V3_SERVER_URL' };
    }
    const normalizedBase = new URL(base.toString());
    if (!normalizedBase.pathname.endsWith('/')) {
      normalizedBase.pathname = `${normalizedBase.pathname}/`;
    }
    const applicationRelativeFileUrl = fileUrl.startsWith('/')
      ? fileUrl.slice(1)
      : fileUrl;
    const content = new URL(applicationRelativeFileUrl, normalizedBase);
    if (
      content.origin !== base.origin ||
      !content.pathname.startsWith(normalizedBase.pathname)
    ) {
      return { ok: false, reason: 'READER_V3_FILE_URL_SCOPE_MISMATCH' };
    }
    return { ok: true, value: content.toString() };
  } catch {
    return { ok: false, reason: 'INVALID_READER_V3_FILE_URL' };
  }
}

function navigationEntry(unit: ReaderBootstrapData['units'][number]): ReaderNavigationEntry {
  return {
    id: unit.id,
    label: unit.title,
    index: unit.index,
    ...(unit.href === undefined || unit.href === null
      ? {}
      : { href: unit.href }),
  };
}

export function mapReaderBootstrapToSource(
  bootstrap: ReaderBootstrapData,
  serverBaseUrl: string,
): ValidationResult<ReaderSource> {
  if (
    bootstrap.book.id !== bootstrap.mediaVersion.workId ||
    bootstrap.mediaVersion.id !== bootstrap.volume.mediaVersionId ||
    bootstrap.readerType !== bootstrap.volume.readerType
  ) {
    return { ok: false, reason: 'INCONSISTENT_READER_V3_BOOTSTRAP' };
  }
  const contentUrl = resolveContentUrl(serverBaseUrl, bootstrap.fileUrl);
  if (!contentUrl.ok) return contentUrl;

  const sourceBase = {
    workId: bootstrap.book.id,
    volumeId: bootstrap.volume.id,
    contentUrl: contentUrl.value,
    contentFingerprint: bootstrap.contentFingerprint,
    ...(bootstrap.volume.pageCount === undefined
      ? {}
      : { totalPages: bootstrap.volume.pageCount }),
  };

  switch (bootstrap.readerType) {
    case 'reflowable':
      if (
        bootstrap.sourceFormat === undefined ||
        bootstrap.sourceFormat === null ||
        bootstrap.mediaVersion.mediaKind !== 'EBOOK'
      ) {
        return { ok: false, reason: 'INCONSISTENT_READER_V3_BOOTSTRAP' };
      }
      return {
        ok: true,
        value: {
          ...sourceBase,
          kind: 'reflowable',
          sourceFormat: bootstrap.sourceFormat,
          navigation: bootstrap.units.map(navigationEntry),
        },
      };
    case 'comic':
      if (bootstrap.mediaVersion.mediaKind !== 'COMIC') {
        return { ok: false, reason: 'INCONSISTENT_READER_V3_BOOTSTRAP' };
      }
      return { ok: true, value: { ...sourceBase, kind: 'comic' } };
    case 'pdf':
      if (bootstrap.mediaVersion.mediaKind !== 'EBOOK') {
        return { ok: false, reason: 'INCONSISTENT_READER_V3_BOOTSTRAP' };
      }
      return { ok: true, value: { ...sourceBase, kind: 'pdf' } };
    case 'audio':
      return { ok: false, reason: 'READER_CORE_AUDIO_NOT_SUPPORTED' };
  }
}

import type { ReaderOpaqueLocator } from '@shuku/reader-core';

type LocatorRecord = Record<string, unknown>;

/** Stable adapter error for a persisted position that the engine cannot use. */
export const LOCATION_RESTORE_FAILED = 'LOCATION_RESTORE_FAILED';

function record(value: unknown): LocatorRecord | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as LocatorRecord
    : null;
}

/**
 * Adapter-owned view of the cross-platform Locator shape. The transport
 * boundary never calls this parser; only an engine adapter may interpret its
 * own Locator to restore a position.
 */
export type StandardReaderLocator = Readonly<{
  href: string;
  type: string;
  locations: Readonly<LocatorRecord>;
}>;

export function parseStandardReaderLocator(locator: ReaderOpaqueLocator | null | undefined): StandardReaderLocator | null {
  const item = record(locator);
  const locations = item ? record(item.locations) : null;
  if (!item || !locations
    || typeof item.href !== 'string' || item.href.trim().length === 0
    || typeof item.type !== 'string' || item.type.trim().length === 0) return null;
  return { href: item.href, type: item.type, locations };
}

export function standardLocatorPosition(locator: StandardReaderLocator) {
  const position = locator.locations.position;
  return typeof position === 'number' && Number.isSafeInteger(position) && position >= 1 ? position : null;
}

export function standardLocatorProgression(locator: StandardReaderLocator) {
  const progression = locator.locations.progression;
  return typeof progression === 'number' && Number.isFinite(progression)
    ? Math.max(0, Math.min(1, progression))
    : null;
}

export function standardLocatorTimeSeconds(locator: StandardReaderLocator) {
  const time = locator.locations.time;
  return typeof time === 'number' && Number.isFinite(time) && time >= 0 ? time : null;
}

export function createStandardReaderLocator(input: {
  href: string;
  type: string;
  position: number;
  progression: number;
  totalProgression: number;
  timeSeconds?: number;
}): ReaderOpaqueLocator {
  return {
    href: input.href,
    type: input.type,
    locations: {
      position: Math.max(1, Math.trunc(input.position)),
      progression: Math.max(0, Math.min(1, input.progression)),
      totalProgression: Math.max(0, Math.min(1, input.totalProgression)),
      ...(input.timeSeconds === undefined ? {} : { time: Math.max(0, input.timeSeconds) })
    }
  };
}

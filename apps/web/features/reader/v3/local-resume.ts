import type { ReaderKind, ReaderLocation, ReflowableFormat } from '@shuku/reader-core';
import type { ProgressMutation } from '../../../lib/reader';

type VisualProgressMutation = ProgressMutation & { location: ReaderLocation };

type LocalResumeContextBase = {
  userId: string;
  volumeId: string;
  contentFingerprint: string;
};

export type LocalResumeContext = LocalResumeContextBase & (
  | { readerKind: 'reflowable'; sourceFormat: ReflowableFormat }
  | { readerKind: Exclude<ReaderKind, 'reflowable'>; sourceFormat?: never }
);

export type StartupResumeDecision = {
  location: ReaderLocation | null;
  percent: number;
  source: 'direct-target' | 'local-pending' | 'server';
  localMutation: VisualProgressMutation | null;
};

function hasVisualReaderLocation(mutation: ProgressMutation): mutation is VisualProgressMutation {
  return mutation.location.kind !== 'audio';
}

function locationForContext(location: ReaderLocation, context: LocalResumeContext): ReaderLocation | null {
  if (context.readerKind === 'reflowable') {
    if (location.kind === 'epub') {
      return {
        kind: 'reflowable',
        format: 'epub',
        cfi: location.cfi,
        href: location.href,
        progression: location.progression
      };
    }
    if (location.kind !== 'reflowable') return null;
    return location.format === context.sourceFormat ? location : null;
  }
  return location.kind === context.readerKind ? location : null;
}

/**
 * Selects only an exact content-scoped mutation. A pending position from a
 * different user, volume, rendition, or reader cannot be restored.
 */
export function newestLocalResume(
  mutations: readonly ProgressMutation[],
  context: LocalResumeContext
): VisualProgressMutation | null {
  let latest: VisualProgressMutation | null = null;
  for (const mutation of mutations) {
    if (!hasVisualReaderLocation(mutation)) continue;
    const normalizedLocation = locationForContext(mutation.location, context);
    if (
      mutation.userId !== context.userId
      || mutation.volumeId !== context.volumeId
      || mutation.contentFingerprint !== context.contentFingerprint
      || !normalizedLocation
    ) continue;

    const normalizedMutation: VisualProgressMutation = normalizedLocation === mutation.location
      ? mutation
      : { ...mutation, location: normalizedLocation };

    if (!latest) {
      latest = normalizedMutation;
      continue;
    }
    if (mutation.clientSequence !== latest.clientSequence) {
      if (mutation.clientSequence > latest.clientSequence) latest = normalizedMutation;
      continue;
    }
    if (mutation.updatedAt > latest.updatedAt) latest = normalizedMutation;
  }
  return latest;
}

/**
 * Reconciles the server snapshot with the durable local outbox. An explicit,
 * validated deep link is user intent and always wins; otherwise the newest
 * exact pending mutation wins over the potentially stale bootstrap response.
 */
export function resolveStartupResume(input: {
  mutations: readonly ProgressMutation[];
  context: LocalResumeContext;
  initialLocation: ReaderLocation | null;
  progressPercent: number;
  hasDirectTarget: boolean;
}): StartupResumeDecision {
  if (input.hasDirectTarget) {
    return {
      location: input.initialLocation,
      percent: input.progressPercent,
      source: 'direct-target',
      localMutation: null
    };
  }

  const localMutation = newestLocalResume(input.mutations, input.context);
  if (localMutation) {
    return {
      location: localMutation.location,
      percent: localMutation.percent,
      source: 'local-pending',
      localMutation
    };
  }

  return {
    location: input.initialLocation,
    percent: input.progressPercent,
    source: 'server',
    localMutation: null
  };
}

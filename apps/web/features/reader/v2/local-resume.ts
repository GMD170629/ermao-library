import type { ReaderKind, ReaderLocation } from '@shuku/reader-core';
import type { ProgressMutation } from '../../../lib/reader-v2';

type VisualProgressMutation = ProgressMutation & { location: ReaderLocation };

export type LocalResumeContext = {
  userId: string;
  editionId: string;
  volumeId?: string | null;
  contentFingerprint: string;
  readerKind: ReaderKind;
};

export type StartupResumeDecision = {
  location: ReaderLocation | null;
  percent: number;
  source: 'direct-target' | 'local-pending' | 'server';
  localMutation: VisualProgressMutation | null;
};

function sameVolume(left: string | null | undefined, right: string | null | undefined) {
  return (left ?? null) === (right ?? null);
}

function hasVisualReaderLocation(mutation: ProgressMutation): mutation is VisualProgressMutation {
  return mutation.location.kind !== 'audio';
}

/**
 * Selects only an exact content-scoped mutation. A pending position from a
 * different user, edition, volume, rendition, or reader cannot be restored.
 */
export function newestLocalResume(
  mutations: readonly ProgressMutation[],
  context: LocalResumeContext
) {
  return mutations.reduce<VisualProgressMutation | null>((latest, mutation) => {
    if (
      mutation.userId !== context.userId
      || mutation.editionId !== context.editionId
      || !sameVolume(mutation.volumeId, context.volumeId)
      || mutation.contentFingerprint !== context.contentFingerprint
      || !hasVisualReaderLocation(mutation)
      || mutation.location.kind !== context.readerKind
    ) return latest;

    if (!latest) return mutation;
    if (mutation.clientSequence !== latest.clientSequence) {
      return mutation.clientSequence > latest.clientSequence ? mutation : latest;
    }
    return mutation.updatedAt > latest.updatedAt ? mutation : latest;
  }, null);
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

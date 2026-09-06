import type { ReaderV5PendingMutation } from '../../lib/reader';

/** v5 detail overlays consume presentation only; Locator remains engine-owned. */
export function localV5ProgressPresentation(progress: ReaderV5PendingMutation | null) {
  return progress?.position.presentation ?? null;
}

export function localV5ProgressPercent(serverProgress: number, progress: ReaderV5PendingMutation | null) {
  return progress?.position.presentation.displayPercent ?? serverProgress;
}

export function latestLocalV5Progress(progresses: readonly ReaderV5PendingMutation[]) {
  return [...progresses].sort((left, right) => (
    right.capturedAtEpochMillis - left.capturedAtEpochMillis
    || right.mutationId.localeCompare(left.mutationId)
  ))[0] ?? null;
}

/** A delayed storage read must not erase a capture received while it was loading. */
export function mergeLocalV5Progress(
  stored: readonly ReaderV5PendingMutation[],
  captured: readonly ReaderV5PendingMutation[]
): Record<string, ReaderV5PendingMutation> {
  const result: Record<string, ReaderV5PendingMutation> = {};
  for (const progress of [...stored, ...captured]) {
    const previous = result[progress.resourceId];
    if (!previous || previous.capturedAtEpochMillis <= progress.capturedAtEpochMillis) {
      result[progress.resourceId] = progress;
    }
  }
  return result;
}

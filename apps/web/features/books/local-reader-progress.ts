import type { ReaderV5ProgressRecord } from '../../lib/reader';

/** v5 detail overlays consume presentation only; Locator remains engine-owned. */
export function localV5ProgressPresentation(progress: ReaderV5ProgressRecord | null) {
  return progress?.position.presentation ?? null;
}

export function localV5ProgressPercent(serverProgress: number, progress: ReaderV5ProgressRecord | null) {
  return progress?.position.presentation.displayPercent ?? serverProgress;
}

export function latestLocalV5Progress(progresses: readonly ReaderV5ProgressRecord[]) {
  return [...progresses].sort((left, right) => (
    right.capturedAtEpochMillis - left.capturedAtEpochMillis
    || right.mutationId.localeCompare(left.mutationId)
  ))[0] ?? null;
}

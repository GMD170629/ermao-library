import type { ExactProgressRecord } from '../../lib/reader/model';

export type LocalProgressScope = {
  userId: string;
  workId: string;
  volumeId: string;
  contentFingerprint: string;
};

export function latestScopedProgress(
  mutations: readonly ExactProgressRecord[],
  scope: LocalProgressScope
) {
  return mutations
    .filter((mutation) => (
      mutation.userId === scope.userId
      && mutation.workId === scope.workId
      && mutation.volumeId === scope.volumeId
      && (mutation.localContentFingerprint ?? mutation.publicationFingerprint) === scope.contentFingerprint
    ))
    .sort((left, right) => right.capturedAtEpochMillis - left.capturedAtEpochMillis)[0] ?? null;
}

export function localProgressProjection(mutation: ExactProgressRecord | null) {
  if (!mutation) return null;
  const location = mutation.location;
  if (!location && mutation.locator) {
    return {
      percent: mutation.displayPercent,
      currentHref: mutation.locator.payload.href,
      position: mutation.locator.payload.locations.position ?? null
    };
  }
  if (!location) return { percent: mutation.displayPercent };
  return { percent: mutation.displayPercent };
}

import type { ExactProgressRecord } from '../../lib/reader/model';

export type LocalProgressScope = {
  userId: string;
  workId: string;
  volumeId: string;
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
    ))
    .sort((left, right) => right.capturedAtEpochMillis - left.capturedAtEpochMillis)[0] ?? null;
}

export function localProgressProjection(mutation: ExactProgressRecord | null) {
  if (!mutation) return null;
  const location = mutation.locator;
  if (location.kind === 'reflowable') {
    return {
      percent: mutation.displayPercent,
      currentHref: location.engineLocator.payload.href,
      position: location.engineLocator.payload.locations.position ?? null
    };
  }
  return { percent: mutation.displayPercent };
}

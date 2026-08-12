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
      && mutation.localContentFingerprint === scope.contentFingerprint
    ))
    .sort((left, right) => right.updatedAtEpochMillis - left.updatedAtEpochMillis)[0] ?? null;
}

export function localProgressProjection(mutation: ExactProgressRecord | null) {
  if (!mutation) return null;
  const location = mutation.location;
  if (location.kind === 'reflowable') {
    const metrics = location.foliate;
    return {
      percent: mutation.percent,
      currentHref: metrics?.toc?.href ?? location.href ?? null,
      currentChapterIndex: metrics?.toc?.index ?? null,
      currentChapterTitle: metrics?.toc?.title ?? null,
      locationCurrent: metrics?.location?.current ?? null,
      locationNext: metrics?.location?.next ?? null,
      locationTotal: metrics?.location?.total ?? null,
      remainingSectionSeconds: metrics?.remainingSeconds?.section ?? null,
      remainingTotalSeconds: metrics?.remainingSeconds?.total ?? null
    };
  }
  if (location.kind === 'pdf') {
    return { percent: mutation.percent, pageNumber: location.pageNumber };
  }
  if (location.kind === 'comic') {
    return { percent: mutation.percent, pageNumber: location.pageIndex };
  }
  return { percent: mutation.percent };
}

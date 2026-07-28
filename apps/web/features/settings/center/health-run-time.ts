export function healthRunElapsedMs(
  startedAt: number,
  finishedAt: number | null | undefined,
  now: number,
): number {
  const end = finishedAt ?? now;
  if (!Number.isFinite(startedAt) || !Number.isFinite(end)) return 0;
  return Math.max(0, end - startedAt);
}

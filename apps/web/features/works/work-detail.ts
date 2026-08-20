import { IMPLICIT_VERSION_SOURCE_KEY, type MediaKind, type VersionResource, type VolumeResource, type WorkView } from '../../types/work';

export function workDetailReturnHref(value: unknown): string {
  if (typeof value !== 'string' || (!value.startsWith('/library?') && value !== '/library')) {
    return '/library';
  }
  try {
    const url = new URL(value, 'https://local.invalid');
    if (url.origin !== 'https://local.invalid' || url.pathname !== '/library') return '/library';
    return `${url.pathname}${url.search}`;
  } catch {
    return '/library';
  }
}

export function workDetailHref(
  workId: string,
  volumeId?: string | null,
  returnTo?: string | null,
  versionId?: string | null
): string {
  const query = new URLSearchParams();
  if (volumeId) query.set('volumeId', volumeId);
  if (versionId) query.set('versionId', versionId);
  if (returnTo) query.set('returnTo', workDetailReturnHref(returnTo));
  const suffix = query.size > 0 ? `?${query}` : '';
  return `/works/${encodeURIComponent(workId)}${suffix}`;
}

export function displayVolumeNumber(volume: VolumeResource, position: number): number {
  return volume.volumeIndex ?? position + 1;
}

export function formatDuration(durationMs: number | null | undefined): string {
  if (!durationMs || durationMs <= 0) return '';
  const totalSeconds = Math.round(durationMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${minutes}:${String(seconds).padStart(2, '0')}`;
}

export function isImplicitVersion(version: Pick<VersionResource, 'sourceKey'>): boolean {
  return version.sourceKey === IMPLICIT_VERSION_SOURCE_KEY;
}

export function versionDisplayTitle(version: VersionResource): string | null {
  if (isImplicitVersion(version)) return null;
  const named = version.sourceName?.trim();
  if (named) return named;
  return version.sourceKey;
}

export function shouldShowVersionHeadings(work: WorkView): boolean {
  return work.versions.length > 1;
}

export function selectedVolumeForWork(work: WorkView, requestedVolumeId?: string | null): VolumeResource | null {
  const volumes = allVisibleVolumes(work);
  return volumes.find((volume) => volume.id === requestedVolumeId)
    ?? volumes.find((volume) => volume.id === work.continueVolumeId)
    ?? volumes.find((volume) => volume.progress < 100)
    ?? volumes[0]
    ?? null;
}

export function selectedVolumeForVersion(
  work: WorkView,
  version: VersionResource | null,
  requestedVolumeId?: string | null
): VolumeResource | null {
  if (!version) return null;
  const volumes = version.volumes.filter((volume) => !volume.hidden);
  return volumes.find((volume) => volume.id === requestedVolumeId)
    ?? volumes.find((volume) => volume.id === work.continueVolumeId)
    ?? volumes.find((volume) => volume.progress < 100)
    ?? volumes[0]
    ?? null;
}

export function allVisibleVolumes(work: WorkView): VolumeResource[] {
  return work.versions.flatMap((version) => version.volumes.filter((volume) => !volume.hidden));
}

export function mediaKindOfVolume(volume: VolumeResource): MediaKind {
  if (volume.classification.suggestedMediaKind) return volume.classification.suggestedMediaKind;
  if (volume.readerType === 'audio') return 'AUDIOBOOK';
  if (volume.readerType === 'comic') return 'COMIC';
  return 'EBOOK';
}

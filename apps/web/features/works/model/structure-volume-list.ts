export const COLLAPSED_STRUCTURE_VOLUME_LIMIT = 10;

export type StructureVolumeList<T> = Readonly<{
  visibleVolumes: readonly T[];
  canToggle: boolean;
}>;

export function structureVolumeList<T>(volumes: readonly T[], expanded: boolean, totalCount = volumes.length): StructureVolumeList<T> {
  return {
    visibleVolumes: expanded ? volumes : volumes.slice(0, COLLAPSED_STRUCTURE_VOLUME_LIMIT),
    canToggle: totalCount > COLLAPSED_STRUCTURE_VOLUME_LIMIT
  };
}

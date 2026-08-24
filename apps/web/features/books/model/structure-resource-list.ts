export const COLLAPSED_STRUCTURE_RESOURCE_LIMIT = 10;

export type StructureResourceList<T> = Readonly<{
  visibleResources: readonly T[];
  canToggle: boolean;
}>;

export function structureResourceList<T>(resources: readonly T[], expanded: boolean, totalCount = resources.length): StructureResourceList<T> {
  return {
    visibleResources: expanded ? resources : resources.slice(0, COLLAPSED_STRUCTURE_RESOURCE_LIMIT),
    canToggle: totalCount > COLLAPSED_STRUCTURE_RESOURCE_LIMIT
  };
}

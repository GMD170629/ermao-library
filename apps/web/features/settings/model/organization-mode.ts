export type OrganizationMode = 'FLAT' | 'VOLUMES';

export const ORGANIZATION_MODES: ReadonlyArray<{
  value: OrganizationMode;
  label: string;
  description: string;
}> = [
  {
    value: 'FLAT',
    label: '单本',
    description: '所有支持文件均独立成书，递归遍历任意目录层级'
  },
  {
    value: 'VOLUMES',
    label: '分卷',
    description: '下级目录作为图书，一个图书可能有多个分卷'
  }
];

export function organizationModeLabel(mode: OrganizationMode): string {
  return ORGANIZATION_MODES.find((option) => option.value === mode)?.label ?? mode;
}

export function organizationModeDescription(mode: OrganizationMode): string {
  return ORGANIZATION_MODES.find((option) => option.value === mode)?.description ?? '';
}

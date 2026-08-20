export type OrganizationMode = 'FLAT' | 'VOLUMES' | 'AUDIOBOOK';

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
    label: '卷册',
    description: '首级目录为作品，第二级目录为版本，更深目录中的每个文件独立成卷'
  },
  {
    value: 'AUDIOBOOK',
    label: '有声书',
    description: '首级目录为作品，之后依次为版本和卷，CD、Disc、Disk 目录仅作分碟'
  }
];

export function organizationModeLabel(mode: OrganizationMode): string {
  return ORGANIZATION_MODES.find((option) => option.value === mode)?.label ?? mode;
}

export function organizationModeDescription(mode: OrganizationMode): string {
  return ORGANIZATION_MODES.find((option) => option.value === mode)?.description ?? '';
}

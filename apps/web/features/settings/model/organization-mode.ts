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
    label: '按目录归组',
    description: '首级目录为图书，第二级目录为可读资源，更深目录中的每个资产独立归组'
  },
  {
    value: 'AUDIOBOOK',
    label: '有声书',
    description: '首级目录为图书，之后依次为可读资源和资产，CD、Disc、Disk 目录仅作分碟'
  }
];

export function organizationModeLabel(mode: OrganizationMode): string {
  return ORGANIZATION_MODES.find((option) => option.value === mode)?.label ?? mode;
}

export function organizationModeDescription(mode: OrganizationMode): string {
  return ORGANIZATION_MODES.find((option) => option.value === mode)?.description ?? '';
}

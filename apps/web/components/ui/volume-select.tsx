'use client';

import { Select } from './select';

export type VolumeSelectItem = {
  id: string;
  title: string;
};

export function VolumeSelect({
  items,
  value,
  onChange,
  disabled = false,
  dark = false,
  compact = false,
  className
}: {
  items: VolumeSelectItem[];
  value?: string | null;
  onChange: (volumeId: string) => void;
  disabled?: boolean;
  dark?: boolean;
  compact?: boolean;
  className?: string;
}) {
  const selectedValue = items.some((item) => item.id === value) ? value! : items[0]?.id;
  if (!selectedValue) return null;

  return (
    <Select
      value={selectedValue}
      options={items.map((item) => ({
        value: item.id,
        label: item.title,
        translate: false
      }))}
      onChange={onChange}
      ariaLabel="切换卷册"
      disabled={disabled}
      size={compact ? 'sm' : 'md'}
      tone={dark ? 'dark' : 'light'}
      className={className}
      menuClassName="[-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    />
  );
}

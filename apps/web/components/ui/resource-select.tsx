'use client';

import { Select } from './select';

export type ResourceSelectItem = {
  id: string;
  title: string;
};

export function ResourceSelect({
  items,
  value,
  onChange,
  disabled = false,
  dark = false,
  compact = false,
  className
}: {
  items: ResourceSelectItem[];
  value?: string | null;
  onChange: (resourceId: string) => void;
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
      ariaLabel="切换资源"
      disabled={disabled}
      size={compact ? 'sm' : 'md'}
      tone={dark ? 'dark' : 'light'}
      className={className}
      menuClassName="[-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    />
  );
}

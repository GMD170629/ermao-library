'use client';

import { BookOpen, Check, Files } from 'lucide-react';
import { cn } from '../../../components/ui/cn';
import { useI18n } from '@/i18n/provider';
import { ORGANIZATION_MODES, type OrganizationMode } from '../model/organization-mode';

const MODE_ICONS = {
  FLAT: Files,
  VOLUMES: BookOpen
} as const;

export function OrganizationModePicker({
  value,
  onChange,
  disabled = false,
  compact = false
}: {
  value: OrganizationMode | null;
  onChange: (value: OrganizationMode) => void;
  disabled?: boolean;
  compact?: boolean;
}) {
  const { t } = useI18n();
  return (
    <div role="radiogroup" aria-label={t('组织方式')} className={cn('grid items-stretch gap-3', compact ? 'md:grid-cols-2' : 'sm:grid-cols-2')}>
      {ORGANIZATION_MODES.map((option) => {
        const Icon = MODE_ICONS[option.value];
        const selected = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-label={t(option.label)}
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            className={cn(
              'group relative flex min-h-40 h-full flex-col rounded-2xl border p-4 text-left transition focus-visible:outline-none focus-visible:ring-4 disabled:cursor-not-allowed disabled:opacity-60',
              selected
                ? 'border-[#C66B3D] bg-[#F2E8D5]/90 shadow-[0_10px_30px_rgba(96,108,56,0.10)] focus-visible:ring-[#C66B3D]/20'
                : 'border-[#B08B6E]/45 bg-[#E8DCC7]/70 hover:border-[#C66B3D]/65 hover:bg-[#F2E8D5]/70 focus-visible:ring-[#8B9D83]/25'
            )}
          >
            <span className="flex h-9 shrink-0 items-start justify-between gap-3">
              <span className={cn('flex h-9 w-9 items-center justify-center rounded-xl', selected ? 'bg-[#C66B3D] text-[#F2E8D5]' : 'bg-[#8B9D83]/20 text-[#606C38]')}>
                <Icon size={18} />
              </span>
              {selected ? <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[#606C38] text-[#F2E8D5]"><Check size={14} /></span> : null}
            </span>
            <span className="mt-3 block shrink-0 text-sm font-semibold text-[#606C38]">{t(option.label)}</span>
            <span className="mt-1.5 block text-xs leading-5 text-[#606C38]/70">{t(option.description)}</span>
          </button>
        );
      })}
    </div>
  );
}

'use client';

import { Languages } from 'lucide-react';
import { Select } from '../ui/select';
import { LOCALE_OPTIONS, type AppLocale } from '../../i18n/config';
import { useI18n } from '../../i18n/provider';

type CompactLanguageSwitcherProps = {
  variant?: 'default' | 'setup';
};

const shortLocaleOptions: ReadonlyArray<{ value: AppLocale; label: string }> = LOCALE_OPTIONS.map(
  (option) => ({
    value: option.value,
    label: option.value === 'zh-CN' ? option.label.slice(-2) : option.label.split(' ')[0]
  })
);

export function CompactLanguageSwitcher({
  variant = 'default'
}: CompactLanguageSwitcherProps) {
  const { locale, setLocale } = useI18n();
  const setup = variant === 'setup';

  function changeLanguage(nextLocale: AppLocale) {
    if (nextLocale === locale) return;
    setLocale(nextLocale);
  }

  return (
    <div className="relative inline-flex shrink-0 items-center">
      <Languages
        size={15}
        strokeWidth={1.9}
        className={`pointer-events-none absolute left-3 z-10 ${setup ? 'text-[#606C38]' : 'text-[#514D48]'}`}
        aria-hidden="true"
      />
      <Select
        value={locale}
        options={shortLocaleOptions.map((option) => ({ ...option, translate: false }))}
        ariaLabel="界面语言"
        onChange={changeLanguage}
        size="sm"
        tone={setup ? 'setup' : 'light'}
        align="right"
        className="min-w-[6.5rem]"
        triggerClassName={`!h-10 !rounded-full !pl-9 !pr-3 !text-xs !font-semibold ${
          setup
            ? '!border-[#B08B6E]/55 !bg-[#E8DCC7] !text-[#606C38] focus:!border-[#C66B3D] focus:!ring-[#C66B3D]/15'
            : '!border-black/[0.11] !bg-white/70 !text-[#514D48] hover:!border-[#EF4D2F]/35 hover:!bg-white/90'
        }`}
        menuClassName={setup ? '!rounded-2xl !p-2' : undefined}
      />
    </div>
  );
}

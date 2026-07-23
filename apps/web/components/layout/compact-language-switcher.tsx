'use client';

import { ChevronDown, Languages } from 'lucide-react';
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
  const { locale, setLocale, t } = useI18n();
  const setup = variant === 'setup';

  function changeLanguage(nextLocale: AppLocale) {
    if (nextLocale === locale) return;
    setLocale(nextLocale);
  }

  return (
    <label
      className={`relative inline-flex h-10 shrink-0 items-center gap-2 rounded-full border px-3 transition focus-within:ring-2 ${
        setup
          ? 'border-[#B08B6E]/45 bg-[#E8DCC7]/70 text-[#606C38] focus-within:border-[#C66B3D] focus-within:ring-[#C66B3D]/20'
          : 'border-black/[0.11] bg-white/70 text-[#514D48] hover:border-[#EF4D2F]/35 focus-within:border-[#EF4D2F]/45 focus-within:ring-[#F6B7A5]/55'
      }`}
      title={t('界面语言')}
    >
      <Languages size={15} strokeWidth={1.9} aria-hidden="true" />
      <select
        value={locale}
        aria-label={t('界面语言')}
        onChange={(event) => changeLanguage(event.target.value as AppLocale)}
        className="min-w-[4.75rem] cursor-pointer appearance-none bg-transparent pr-5 text-xs font-semibold outline-none"
      >
        {shortLocaleOptions.map((option) => (
          <option key={option.value} value={option.value} data-i18n-skip>
            {option.label}
          </option>
        ))}
      </select>
      <ChevronDown size={13} strokeWidth={2} className="pointer-events-none absolute right-2.5" aria-hidden="true" />
    </label>
  );
}

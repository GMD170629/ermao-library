'use client';

import { Languages } from 'lucide-react';
import { useState } from 'react';
import { useToast } from '../../../components/ui/feedback';
import { LOCALE_OPTIONS, type AppLocale } from '../../../i18n/config';
import { useI18n } from '../../../i18n/provider';
import { currentUserId, saveAccountPreferences, userDevicePreferenceKey } from '../../../lib/user-preferences';

export function LanguageSettings() {
  const { locale, setLocale, t } = useI18n();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function changeLanguage(nextLocale: AppLocale) {
    if (nextLocale === locale || busy) return;
    setBusy(true);
    try {
      await saveAccountPreferences({ locale: nextLocale });
      window.localStorage.setItem(userDevicePreferenceKey('shuku.locale', currentUserId()), nextLocale);
      setLocale(nextLocale);
      toast.success(t('界面语言已更新'));
    } catch (reason) {
      toast.error(
        t('保存语言设置失败'),
        reason instanceof Error ? t(reason.message) : t('请稍后重试')
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="language-settings-title" className="rounded-[20px] border border-[#E2DED8] bg-white p-4 sm:p-5">
      <div className="grid gap-4 sm:grid-cols-[minmax(14rem,1fr)_minmax(18rem,26rem)] sm:items-center">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#FCE5DE] text-[#D94A2E]">
            <Languages size={18} aria-hidden="true" />
          </div>
          <div>
            <h3 id="language-settings-title" className="text-base font-semibold text-[#272522]">{t('界面语言')}</h3>
            <p className="mt-0.5 text-xs leading-5 text-[#77716A]">
              {t('选择整个应用使用的语言。设置会同步到登录页、阅读器和 PWA。')}
            </p>
          </div>
        </div>

        <fieldset className="grid grid-cols-2 gap-2" disabled={busy}>
        <legend className="sr-only">{t('选择界面语言')}</legend>
        {LOCALE_OPTIONS.map((option) => {
          const selected = option.value === locale;
          return (
            <label
              key={option.value}
              className={`flex cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2.5 transition ${
                selected
                  ? 'border-[#EF8C73] bg-[#FFF2ED] ring-2 ring-[#FAD9D0]'
                  : 'border-[#DEDAD4] bg-[#FCFBF9] hover:border-[#CFC9C1]'
              } ${busy ? 'cursor-wait opacity-70' : ''}`}
            >
              <input
                type="radio"
                name="application-language"
                value={option.value}
                checked={selected}
                onChange={() => void changeLanguage(option.value)}
                className="h-4 w-4 accent-[#E9583A]"
              />
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-[#2E2B28]" data-i18n-skip>{option.label}</span>
              </span>
            </label>
          );
        })}
        </fieldset>
      </div>
      {busy ? <p className="mt-3 text-sm text-[#77716A]" role="status">{t('正在切换语言…')}</p> : null}
    </section>
  );
}

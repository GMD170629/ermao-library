'use client';

import { Languages } from 'lucide-react';
import { useState } from 'react';
import { useToast } from '../../../components/ui/feedback';
import { LOCALE_OPTIONS, type AppLocale } from '../../../i18n/config';
import { useI18n } from '../../../i18n/provider';

type SettingsPayload = {
  ok: boolean;
  data?: { settings?: { language?: unknown } };
  error?: { code?: string; message?: string };
};

export function LanguageSettings() {
  const { locale, setLocale, t } = useI18n();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function changeLanguage(nextLocale: AppLocale) {
    if (nextLocale === locale || busy) return;
    setBusy(true);
    try {
      const response = await fetch('/api/system-settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: { language: nextLocale } })
      });
      const payload = await response.json() as SettingsPayload;
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error?.message ?? t('保存语言设置失败'));
      }
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
    <section aria-labelledby="language-settings-title" className="rounded-[22px] border border-[#E2DED8] bg-white p-5 sm:p-6">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#FCE5DE] text-[#D94A2E]">
          <Languages size={20} aria-hidden="true" />
        </div>
        <div>
          <h3 id="language-settings-title" className="text-lg font-semibold text-[#272522]">{t('界面语言')}</h3>
          <p className="mt-1 text-sm leading-6 text-[#77716A]">
            {t('选择整个应用使用的语言。设置会同步到登录页、阅读器和 PWA。')}
          </p>
        </div>
      </div>

      <fieldset className="mt-5 grid gap-3 sm:grid-cols-2" disabled={busy}>
        <legend className="sr-only">{t('选择界面语言')}</legend>
        {LOCALE_OPTIONS.map((option) => {
          const selected = option.value === locale;
          return (
            <label
              key={option.value}
              className={`flex cursor-pointer items-center gap-3 rounded-2xl border px-4 py-3.5 transition ${
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
                <span className="mt-0.5 block text-xs text-[#817A73]">{option.value}</span>
              </span>
            </label>
          );
        })}
      </fieldset>
      {busy ? <p className="mt-3 text-sm text-[#77716A]" role="status">{t('正在切换语言…')}</p> : null}
    </section>
  );
}

'use client';

import { Check, RotateCcw, Save } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Button } from '../../../components/ui/button';
import { cn } from '../../../components/ui/cn';
import { useToast } from '../../../components/ui/feedback';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import {
  importPreferenceSettingKeys as settingKeys,
  loadImportPreferenceSettings,
  saveImportPreferenceSettings
} from '../api/import-preferences-client';
import { allImportExtensions, importFormatGroups } from '../../imports/public';

const formatGroups = importFormatGroups;
const allExtensions = allImportExtensions;
type FormatGroupId = (typeof formatGroups)[number]['id'];

function formatGroupLabel(id: FormatGroupId, translate: (message: string) => string) {
  if (id === 'ebook') return translate('电子书');
  if (id === 'document-comic') return translate('文档与漫画');
  if (id === 'common-audio') return translate('常用 Web 音频');
  return translate('专业/兼容音频');
}

type ImportPreferences = {
  allowedExtensions: string[];
  ignorePatterns: string;
};

const defaultPreferences: ImportPreferences = {
  allowedExtensions: allExtensions,
  ignorePatterns: ''
};

function normalizePreferences(settings: Record<string, unknown> | undefined): ImportPreferences {
  const rawExtensions = settings?.[settingKeys.allowedExtensions];
  const extensions = Array.isArray(rawExtensions)
    ? allExtensions.filter((extension) => rawExtensions.includes(extension))
    : allExtensions;
  return {
    allowedExtensions: extensions,
    ignorePatterns: typeof settings?.[settingKeys.ignorePatterns] === 'string' ? settings[settingKeys.ignorePatterns] as string : ''
  };
}

export function ImportPreferencesPanel() {
  const { t: i18nAttribute } = useAttributeI18n();
  const toast = useToast();
  const [preferences, setPreferences] = useState(defaultPreferences);
  const [saved, setSaved] = useState(defaultPreferences);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [hasUserEdits, setHasUserEdits] = useState(false);
  const changed = useMemo(
    () => hasUserEdits || JSON.stringify(preferences) !== JSON.stringify(saved),
    [hasUserEdits, preferences, saved]
  );
  const allSelected = preferences.allowedExtensions.length === allExtensions.length;

  useEffect(() => {
    let active = true;
    loadImportPreferenceSettings()
      .then((settings) => {
        if (!active) return;
        const next = normalizePreferences(settings);
        setPreferences(next);
        setSaved(next);
        setHasUserEdits(false);
      })
      .catch((reason) => {
        if (active) toast.error('读取导入偏好失败', reason instanceof Error ? reason.message : '请稍后重试');
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [toast]);

  function editPreferences(update: (current: ImportPreferences) => ImportPreferences) {
    setPreferences(update);
    setHasUserEdits(true);
  }

  function toggleExtension(extension: string) {
    editPreferences((current) => ({
      ...current,
      allowedExtensions: current.allowedExtensions.includes(extension)
        ? current.allowedExtensions.filter((item) => item !== extension)
        : allExtensions.filter((item) => item === extension || current.allowedExtensions.includes(item))
    }));
  }

  async function savePreferences() {
    setSaving(true);
    try {
      await saveImportPreferenceSettings({
        [settingKeys.allowedExtensions]: preferences.allowedExtensions,
        [settingKeys.ignorePatterns]: preferences.ignorePatterns
      });
      const next = normalizePreferences({
        [settingKeys.allowedExtensions]: preferences.allowedExtensions,
        [settingKeys.ignorePatterns]: preferences.ignorePatterns
      });
      setPreferences(next);
      setSaved(next);
      setHasUserEdits(false);
      window.dispatchEvent(new Event('shuku:settings-changed'));
      toast.success('导入偏好已保存', '新的规则会用于后续上传、书库扫描和后台导入。');
    } catch (reason) {
      toast.error('保存导入偏好失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-8" aria-busy={loading || saving || undefined}>
      <section aria-labelledby="extensions-title" className="border-b border-[#E5E0DA] pb-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h3 id="extensions-title" className="text-lg font-semibold text-[#2A2825]"><I18nText>允许导入的文件后缀</I18nText></h3>
            <p className="mt-1 text-sm leading-6 text-[#77716A]"><I18nText>默认全部开启。关闭后缀会同时影响手动上传、书库和后台导入。</I18nText></p>
          </div>
          <button
            type="button"
            disabled={loading}
            onClick={() => editPreferences((current) => ({ ...current, allowedExtensions: allSelected ? [] : allExtensions }))}
            className="min-h-10 rounded-xl px-3 text-sm font-medium text-[#D94724] hover:bg-[#FFF3EE] disabled:opacity-50"
          >
            {allSelected ? i18nAttribute("全部关闭") : i18nAttribute("全部开启")}
          </button>
        </div>
        <div className="mt-5 grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {formatGroups.map((group) => (
            <fieldset key={group.id}>
              <legend className="mb-2 text-sm font-medium text-[#4F4B47]">{formatGroupLabel(group.id, i18nAttribute)}</legend>
              <div className="flex flex-wrap gap-2">
                {group.formats.map((extension) => {
                  const selected = preferences.allowedExtensions.includes(extension);
                  return (
                    <button
                      key={extension}
                      type="button"
                      aria-pressed={selected}
                      disabled={loading}
                      onClick={() => toggleExtension(extension)}
                      className={cn(
                        'inline-flex min-h-10 items-center gap-1.5 rounded-xl border px-3 text-sm font-medium uppercase transition-colors disabled:opacity-50',
                        selected ? 'border-[#F2A18C] bg-[#FFF2ED] text-[#D94724]' : 'border-[#DED8D1] bg-white text-[#77716A] hover:border-[#C9C2BA]'
                      )}
                    >
                      {selected ? <Check size={14} aria-hidden="true" /> : null}
                      {extension.slice(1)}
                    </button>
                  );
                })}
              </div>
            </fieldset>
          ))}
        </div>
      </section>

      <section aria-labelledby="ignore-title">
        <h3 id="ignore-title" className="text-lg font-semibold text-[#2A2825]"><I18nText>全局导入忽略规则</I18nText></h3>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-[#77716A]"><I18nText>每行一条规则，支持通配符。规则会与每个书库自己的忽略规则叠加。</I18nText></p>
        <textarea
          value={preferences.ignorePatterns}
          disabled={loading}
          onChange={(event) => editPreferences((current) => ({ ...current, ignorePatterns: event.target.value }))}
          placeholder={i18nAttribute("例如：\n*.part\n*.tmp\n~$*\n扫描版*\n*/缓存/*")}
          rows={6}
          className="mt-4 w-full max-w-3xl resize-y rounded-xl border border-[#DED8D1] bg-white px-3.5 py-3 font-mono text-sm leading-6 text-[#2A2825] outline-none placeholder:text-[#B4ADA6] focus:border-[#F09A83] focus:ring-2 focus:ring-[#FFE3DA] disabled:bg-[#F7F4F1]"
        />
      </section>

      <div className="flex flex-wrap justify-end gap-3 border-t border-[#E5E0DA] pt-6">
        <Button
          variant="secondary"
          icon={RotateCcw}
          disabled={!changed || loading || saving}
          onClick={() => {
            setPreferences(saved);
            setHasUserEdits(false);
          }}
        >
          <I18nText>撤销更改</I18nText></Button>
        <Button icon={Save} loading={saving} loadingText={i18nAttribute("保存中")} disabled={!changed || loading} onClick={() => void savePreferences()}>
          <I18nText>保存偏好</I18nText></Button>
      </div>
    </div>
  );
}

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

const formatGroups = [
  { label: '电子书', formats: ['.epub', '.mobi', '.azw', '.azw3', '.prc', '.fb2', '.txt'] },
  { label: '文档与漫画', formats: ['.pdf', '.cbz', '.zip', '.cbr', '.rar'] },
  { label: '有声书', formats: ['.m4b', '.m4a', '.mp3'] }
] as const;
const allExtensions = formatGroups.flatMap((group) => [...group.formats]);

type ImportPreferences = {
  stabilityEnabled: boolean;
  stabilitySeconds: number;
  allowedExtensions: string[];
  ignorePatterns: string;
};

const defaultPreferences: ImportPreferences = {
  stabilityEnabled: false,
  stabilitySeconds: 2,
  allowedExtensions: allExtensions,
  ignorePatterns: ''
};

function booleanSetting(value: unknown, fallback: boolean) {
  if (typeof value === 'boolean') return value;
  if (value === 'true') return true;
  if (value === 'false') return false;
  return fallback;
}

function normalizePreferences(settings: Record<string, unknown> | undefined): ImportPreferences {
  const rawExtensions = settings?.[settingKeys.allowedExtensions];
  const extensions = Array.isArray(rawExtensions)
    ? allExtensions.filter((extension) => rawExtensions.includes(extension))
    : allExtensions;
  const rawSeconds = Number(settings?.[settingKeys.stabilitySeconds] ?? defaultPreferences.stabilitySeconds);
  return {
    stabilityEnabled: booleanSetting(settings?.[settingKeys.stabilityEnabled], false),
    stabilitySeconds: Number.isFinite(rawSeconds) ? Math.min(300, Math.max(0.5, rawSeconds)) : 2,
    allowedExtensions: extensions,
    ignorePatterns: typeof settings?.[settingKeys.ignorePatterns] === 'string' ? settings[settingKeys.ignorePatterns] as string : ''
  };
}

function Switch({ checked, onChange, label, disabled = false }: { checked: boolean; onChange: (checked: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative h-7 w-12 shrink-0 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#FFC9B9] disabled:cursor-not-allowed disabled:opacity-50',
        checked ? 'bg-[#FF4F2A]' : 'bg-[#C9C4BE]'
      )}
    >
      <span className={cn('absolute left-1 top-1 h-5 w-5 rounded-full bg-white shadow-sm transition-transform', checked ? 'translate-x-5' : 'translate-x-0')} />
    </button>
  );
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
        [settingKeys.stabilityEnabled]: preferences.stabilityEnabled,
        [settingKeys.stabilitySeconds]: preferences.stabilitySeconds,
        [settingKeys.allowedExtensions]: preferences.allowedExtensions,
        [settingKeys.ignorePatterns]: preferences.ignorePatterns
      });
      const next = normalizePreferences({
        [settingKeys.stabilityEnabled]: preferences.stabilityEnabled,
        [settingKeys.stabilitySeconds]: preferences.stabilitySeconds,
        [settingKeys.allowedExtensions]: preferences.allowedExtensions,
        [settingKeys.ignorePatterns]: preferences.ignorePatterns
      });
      setPreferences(next);
      setSaved(next);
      setHasUserEdits(false);
      window.dispatchEvent(new Event('shuku:settings-changed'));
      toast.success('导入偏好已保存', '新的规则会用于后续上传、监控扫描和后台导入。');
    } catch (reason) {
      toast.error('保存导入偏好失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-8" aria-busy={loading || saving || undefined}>
      <section aria-labelledby="stability-title" className="border-b border-[#E5E0DA] pb-8">
        <div className="flex items-start justify-between gap-5">
          <div>
            <h3 id="stability-title" className="text-lg font-semibold text-[#2A2825]"><I18nText>文件稳定性检查</I18nText></h3>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-[#77716A]"><I18nText>监控目录发现文件后，确认文件大小与修改时间不再变化，再加入导入队列。</I18nText></p>
          </div>
          <Switch
            checked={preferences.stabilityEnabled}
            onChange={(stabilityEnabled) => editPreferences((current) => ({ ...current, stabilityEnabled }))}
            label={i18nAttribute("导入时检查文件稳定性")}
            disabled={loading}
          />
        </div>
        <label className="mt-5 block max-w-sm text-sm font-medium text-[#4F4B47]">
          <I18nText>检查时间</I18nText><span className="mt-2 flex items-center overflow-hidden rounded-xl border border-[#DED8D1] bg-white focus-within:border-[#F09A83] focus-within:ring-2 focus-within:ring-[#FFE3DA]">
            <input
              type="number"
              min="0.5"
              max="300"
              step="0.5"
              value={preferences.stabilitySeconds}
              disabled={!preferences.stabilityEnabled || loading}
              onChange={(event) => editPreferences((current) => ({ ...current, stabilitySeconds: Number(event.target.value) }))}
              onBlur={() => setPreferences((current) => ({ ...current, stabilitySeconds: Math.min(300, Math.max(0.5, Number(current.stabilitySeconds) || 2)) }))}
              className="min-h-11 min-w-0 flex-1 bg-transparent px-3.5 text-sm text-[#2A2825] outline-none disabled:bg-[#F7F4F1] disabled:text-[#AAA39C]"
            />
            <span className="px-3.5 text-sm text-[#77716A]"><I18nText>秒</I18nText></span>
          </span>
          <span className="mt-2 block text-xs font-normal leading-5 text-[#77716A]"><I18nText>最短 0.5 秒，最长 300 秒；时间越长，越适合仍在复制中的大文件。</I18nText></span>
        </label>
      </section>

      <section aria-labelledby="extensions-title" className="border-b border-[#E5E0DA] pb-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h3 id="extensions-title" className="text-lg font-semibold text-[#2A2825]"><I18nText>允许导入的文件后缀</I18nText></h3>
            <p className="mt-1 text-sm leading-6 text-[#77716A]"><I18nText>默认全部开启。关闭后缀会同时影响手动上传、监控文件夹和后台导入。</I18nText></p>
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
            <fieldset key={group.label}>
              <legend className="mb-2 text-sm font-medium text-[#4F4B47]">{group.label}</legend>
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
        <p className="mt-1 max-w-3xl text-sm leading-6 text-[#77716A]"><I18nText>每行一条规则，支持通配符。规则会与每个监控文件夹自己的忽略规则叠加。</I18nText></p>
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

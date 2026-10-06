'use client';

import { Clock3, FolderSync, Save } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button } from '../../../components/ui/button';
import { useToast } from '../../../components/ui/feedback';
import { I18nText, useI18n } from '@/i18n/provider';
import {
  loadLibraryScanSettings,
  saveLibraryScanSettings,
  type LibraryScanSettings
} from '../api/library-scan-settings-client';

const defaults: LibraryScanSettings = { watchEnabled: true, intervalMinutes: 1440 };

export function LibraryScanSettingsPanel() {
  const { t } = useI18n();
  const toast = useToast();
  const [settings, setSettings] = useState<LibraryScanSettings>(defaults);
  const [saved, setSaved] = useState<LibraryScanSettings>(defaults);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const changed = settings.watchEnabled !== saved.watchEnabled || settings.intervalMinutes !== saved.intervalMinutes;

  useEffect(() => {
    const controller = new AbortController();
    loadLibraryScanSettings(controller.signal)
      .then((value) => {
        setSettings(value);
        setSaved(value);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) toast.error('读取自动扫描设置失败', reason instanceof Error ? reason.message : '请稍后重试');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [toast]);

  async function save() {
    setSaving(true);
    try {
      const value = await saveLibraryScanSettings(settings);
      setSettings(value);
      setSaved(value);
      toast.success('自动扫描设置已保存', value.intervalMinutes === 0 ? '定时扫描已关闭。' : '定时扫描已开启，每 24 小时执行一次。');
    } catch (reason) {
      toast.error('保存自动扫描设置失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-3xl space-y-8" aria-busy={loading || saving || undefined}>
      <section className="border-b border-[#E5E0DA] pb-8" aria-labelledby="watch-title">
        <div className="flex items-start justify-between gap-6">
          <div className="flex gap-3">
            <FolderSync className="mt-0.5 text-[#D94724]" size={20} aria-hidden="true" />
            <div>
              <h3 id="watch-title" className="text-lg font-semibold text-[#2A2825]"><I18nText>实时监听文件变化</I18nText></h3>
              <p className="mt-1 text-sm leading-6 text-[#77716A]"><I18nText>新增、修改、删除和移动会在变化稳定后扫描受影响目录，同步书库数据。</I18nText></p>
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={settings.watchEnabled}
            disabled={loading}
            onClick={() => setSettings((current) => ({ ...current, watchEnabled: !current.watchEnabled }))}
            className={`relative mt-1 h-7 w-12 shrink-0 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--visual-color-app-focus-ring)] focus-visible:ring-offset-2 motion-reduce:transition-none disabled:opacity-50 ${settings.watchEnabled ? 'bg-[#E64A2E]' : 'bg-[#C8C2BB]'}`}
          >
            <span aria-hidden="true" className={`absolute left-1 top-1 h-5 w-5 rounded-full bg-white transition-transform motion-reduce:transition-none ${settings.watchEnabled ? 'translate-x-5' : 'translate-x-0'}`} />
            <span className="sr-only"><I18nText>实时监听</I18nText></span>
          </button>
        </div>
      </section>

      <section aria-labelledby="interval-title">
        <div className="flex items-start justify-between gap-6">
          <div className="flex min-w-0 gap-3">
            <Clock3 className="mt-0.5 shrink-0 text-[#D94724]" size={20} aria-hidden="true" />
            <div>
              <h3 id="interval-title" className="text-lg font-semibold text-[#2A2825]"><I18nText>定时扫描书库</I18nText></h3>
              <p className="mt-1 text-sm leading-6 text-[#77716A]"><I18nText>开启后每 24 小时扫描一次所有启用的书库，同步停机或监听不可用期间遗漏的文件变化。</I18nText></p>
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-labelledby="interval-title"
            aria-checked={settings.intervalMinutes !== 0}
            disabled={loading || saving}
            onClick={() => setSettings((current) => ({ ...current, intervalMinutes: current.intervalMinutes === 0 ? 1440 : 0 }))}
            className={`relative mt-1 h-7 w-12 shrink-0 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--visual-color-app-focus-ring)] focus-visible:ring-offset-2 motion-reduce:transition-none disabled:opacity-50 ${settings.intervalMinutes !== 0 ? 'bg-[#E64A2E]' : 'bg-[#C8C2BB]'}`}
          >
            <span aria-hidden="true" className={`absolute left-1 top-1 h-5 w-5 rounded-full bg-white transition-transform motion-reduce:transition-none ${settings.intervalMinutes !== 0 ? 'translate-x-5' : 'translate-x-0'}`} />
          </button>
        </div>
        <p className="mt-4 rounded-xl bg-[#F7F4F1] px-4 py-3 text-sm leading-6 text-[#6F6963]"><I18nText>实时监听与定时扫描可分别关闭，手动扫描仍可使用。仅成功读取的目录会更新，访问失败时保留该目录的数据。</I18nText></p>
      </section>

      <div className="flex justify-end border-t border-[#E5E0DA] pt-6">
        <Button icon={Save} loading={saving} loadingText={t('保存中')} disabled={loading || !changed} onClick={() => void save()}>
          <I18nText>保存自动扫描设置</I18nText>
        </Button>
      </div>
    </div>
  );
}

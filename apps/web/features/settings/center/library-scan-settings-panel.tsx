'use client';

import { Clock3, FolderSync, Save } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button } from '../../../components/ui/button';
import { useToast } from '../../../components/ui/feedback';
import { Select } from '../../../components/ui/select';
import { I18nText, useI18n } from '@/i18n/provider';
import {
  loadLibraryScanSettings,
  saveLibraryScanSettings,
  type LibraryScanSettings
} from '../api/library-scan-settings-client';

const intervalOptions = [5, 15, 30, 60, 180, 360, 720, 1440] as const;
const defaults: LibraryScanSettings = { watchEnabled: true, intervalMinutes: 30 };

function intervalLabel(minutes: number, translate: (message: string) => string): string {
  if (minutes === 5) return translate('5 分钟');
  if (minutes === 15) return translate('15 分钟');
  if (minutes === 30) return translate('30 分钟');
  if (minutes === 60) return translate('1 小时');
  if (minutes === 180) return translate('3 小时');
  if (minutes === 360) return translate('6 小时');
  if (minutes === 720) return translate('12 小时');
  return translate('24 小时');
}

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
      toast.success('自动扫描设置已保存', '新的扫描周期从现在开始计算。');
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
              <h3 id="watch-title" className="text-lg font-semibold text-[#2A2825]"><I18nText>实时监听新增文件</I18nText></h3>
              <p className="mt-1 text-sm leading-6 text-[#77716A]"><I18nText>新增文件、目录或移入书库的内容会在复制稳定后自动入库。</I18nText></p>
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={settings.watchEnabled}
            disabled={loading}
            onClick={() => setSettings((current) => ({ ...current, watchEnabled: !current.watchEnabled }))}
            className={`relative mt-1 h-7 w-12 shrink-0 rounded-full transition-colors disabled:opacity-50 ${settings.watchEnabled ? 'bg-[#E64A2E]' : 'bg-[#C8C2BB]'}`}
          >
            <span className={`absolute top-1 h-5 w-5 rounded-full bg-white transition-transform ${settings.watchEnabled ? 'translate-x-6' : 'translate-x-1'}`} />
            <span className="sr-only"><I18nText>实时监听</I18nText></span>
          </button>
        </div>
      </section>

      <section aria-labelledby="interval-title">
        <div className="flex gap-3">
          <Clock3 className="mt-0.5 text-[#D94724]" size={20} aria-hidden="true" />
          <div>
            <h3 id="interval-title" className="text-lg font-semibold text-[#2A2825]"><I18nText>周期扫描间隔</I18nText></h3>
            <p className="mt-1 text-sm leading-6 text-[#77716A]"><I18nText>所有启用书库共用一个周期扫描，用于补回停机或监听不可用期间遗漏的新增内容。</I18nText></p>
          </div>
        </div>
        <label className="mt-5 block max-w-xs text-sm font-medium text-[#4F4B47]">
          <span className="mb-2 block"><I18nText>扫描频率</I18nText></span>
          <Select
            value={String(settings.intervalMinutes)}
            disabled={loading}
            onChange={(value) => setSettings((current) => ({ ...current, intervalMinutes: Number(value) }))}
            ariaLabel="扫描频率"
            className="w-full"
            options={intervalOptions.map((minutes) => ({ value: String(minutes), label: intervalLabel(minutes, t), translate: false }))}
          />
        </label>
        <p className="mt-4 rounded-xl bg-[#F7F4F1] px-4 py-3 text-sm leading-6 text-[#6F6963]"><I18nText>实时监听关闭后，周期扫描仍会继续运行。普通文件修改、移出和删除暂不会触发同步。</I18nText></p>
      </section>

      <div className="flex justify-end border-t border-[#E5E0DA] pt-6">
        <Button icon={Save} loading={saving} loadingText={t('保存中')} disabled={loading || !changed} onClick={() => void save()}>
          <I18nText>保存自动扫描设置</I18nText>
        </Button>
      </div>
    </div>
  );
}

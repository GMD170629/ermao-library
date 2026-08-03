'use client';

import { BookOpenText, Copy } from 'lucide-react';
import { useEffect, useState } from 'react';
import { cn } from '../../../components/ui/cn';
import { useToast } from '../../../components/ui/feedback';
import { useI18n } from '../../../i18n/provider';
import { loadOpdsSettings, saveOpdsSettings, type OpdsSystemSettings } from '../api/opds-settings-client';
import { initialOpdsPublicBaseUrl } from '../model/opds-settings';
import { SettingsCenterShell } from './settings-center-shell';

export function OpdsSettingsPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [settings, setSettings] = useState<OpdsSystemSettings>();
  const [publicBaseUrl, setPublicBaseUrl] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void loadOpdsSettings(controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) {
          setSettings(next);
          setPublicBaseUrl(initialOpdsPublicBaseUrl(next.publicBaseUrl, window.location.origin));
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) toast.error(t('读取 OPDS 配置失败'), reason instanceof Error ? reason.message : t('请稍后重试'));
      });
    return () => controller.abort();
  }, [t, toast]);

  async function toggleEnabled() {
    if (!settings || saving) return;
    setSaving(true);
    try {
      const next = await saveOpdsSettings(!settings.enabled, publicBaseUrl || window.location.origin);
      setSettings(next);
      setPublicBaseUrl(next.publicBaseUrl ?? publicBaseUrl);
      toast.success(t(next.enabled ? 'OPDS 已开启' : 'OPDS 已关闭'));
    } catch (reason) {
      toast.error(t('保存 OPDS 配置失败'), reason instanceof Error ? reason.message : t('请稍后重试'));
    } finally {
      setSaving(false);
    }
  }

  async function savePublicBaseUrl() {
    if (!settings?.enabled || saving) return;
    setSaving(true);
    try {
      const next = await saveOpdsSettings(true, publicBaseUrl);
      setSettings(next);
      setPublicBaseUrl(next.publicBaseUrl ?? publicBaseUrl);
      toast.success(t('OPDS 地址已保存'));
    } catch (reason) {
      toast.error(t('保存 OPDS 配置失败'), reason instanceof Error ? reason.message : t('请稍后重试'));
    } finally {
      setSaving(false);
    }
  }

  async function copyCatalogUrl() {
    if (!settings?.catalogUrl) return;
    try {
      await navigator.clipboard.writeText(settings.catalogUrl);
      toast.success(t('OPDS 地址已复制'));
    } catch {
      toast.error(t('复制失败，请手动复制地址'));
    }
  }

  return (
    <SettingsCenterShell title="OPDS" description="控制第三方阅读器是否可以通过 OPDS 访问书库。">
      <div className="max-w-[920px] space-y-4">
        <section aria-labelledby="opds-toggle-title" className="rounded-[20px] border border-[#E2DED8] bg-white p-5">
          <div className="flex items-start justify-between gap-5">
            <div className="flex min-w-0 gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#FCE5DE] text-[#D94A2E]">
                <BookOpenText size={20} aria-hidden="true" />
              </div>
              <div>
                <h3 id="opds-toggle-title" className="font-semibold text-[#272522]">{t('启用 OPDS 服务')}</h3>
                <p className="mt-1 text-sm leading-6 text-[#77716A]">
                  {t(settings?.enabled ? '第三方 OPDS 阅读器现在可以连接此书库。' : '关闭后，所有 OPDS 地址都会立即停止访问。')}
                </p>
              </div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={settings?.enabled ?? false}
              aria-label={t('启用 OPDS 服务')}
              disabled={!settings || saving}
              onClick={() => void toggleEnabled()}
              className={cn(
                'relative mt-1 h-7 w-12 shrink-0 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#FFC9B9] disabled:cursor-not-allowed disabled:opacity-50',
                settings?.enabled ? 'bg-[#FF4F2A]' : 'bg-[#C9C4BE]'
              )}
            >
              <span className={cn('absolute left-1 top-1 h-5 w-5 rounded-full bg-white shadow-sm transition-transform', settings?.enabled ? 'translate-x-5' : 'translate-x-0')} />
            </button>
          </div>

        </section>

        {settings?.enabled ? (
          <section aria-labelledby="opds-address-title" className="rounded-[20px] border border-[#E2DED8] bg-white p-5">
            <h3 id="opds-address-title" className="font-semibold text-[#272522]">{t('公开 URL')}</h3>
            <p className="mt-1 text-sm leading-6 text-[#77716A]">{t('默认使用当前页面的地址；如果阅读器通过其他域名访问，请在这里修改。')}</p>
            <div className="mt-3 flex flex-col gap-2 sm:flex-row">
              <input
                type="url"
                value={publicBaseUrl}
                onChange={(event) => setPublicBaseUrl(event.target.value)}
                aria-label={t('OPDS 公开 URL')}
                placeholder="https://books.example.com"
                data-i18n-skip
                className="min-w-0 flex-1 rounded-xl border border-[#DEDAD4] bg-white px-3 py-2.5 text-sm text-[#3A3632] outline-none focus:border-[#EF4D2F] focus:ring-2 focus:ring-[#F9DED4]"
              />
              <button type="button" disabled={saving} onClick={() => void savePublicBaseUrl()} className="rounded-xl bg-[#EF4D2F] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#D94329] disabled:cursor-not-allowed disabled:opacity-50">
                {t('保存地址')}
              </button>
            </div>

            {settings.catalogUrl ? (
              <>
                <h3 className="mt-6 font-semibold text-[#272522]">{t('OPDS 地址')}</h3>
                <div className="mt-3 flex items-stretch gap-2">
                  <code className="min-w-0 flex-1 overflow-x-auto rounded-xl bg-[#F7F5F2] px-3 py-2.5 text-sm text-[#3A3632]" data-i18n-skip>{settings.catalogUrl}</code>
                  <button type="button" onClick={() => void copyCatalogUrl()} aria-label={t('复制 OPDS 地址')} className="rounded-xl border border-[#DEDAD4] px-3 text-[#59544E] hover:bg-[#F7F5F2] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#FFC9B9]">
                    <Copy size={18} aria-hidden="true" />
                  </button>
                </div>
              </>
            ) : null}

            <h3 className="mt-6 font-semibold text-[#272522]">{t('连接说明')}</h3>
            <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm leading-6 text-[#66605A]">
              <li>{t('在支持 OPDS 1.2 的阅读器中新增目录，并填写上方地址。')}</li>
              <li>{t('用户名填写你的登录邮箱，密码填写当前账号密码。')}</li>
              <li>{t('漫画客户端可使用 PSE 页面流；兼容客户端可同步阅读进度。')}</li>
              <li>{t('修改账号密码或停用账号后，原连接会立即失效。')}</li>
            </ol>
            <p className="mt-5 rounded-xl bg-[#FFF4EF] p-3 text-xs leading-5 text-[#8A4634]">
              {t('第三方阅读器会保存你的主密码，目前不能单独撤销某台设备。请只在可信设备上通过 HTTPS 使用。')}
            </p>
          </section>
        ) : null}
      </div>
    </SettingsCenterShell>
  );
}

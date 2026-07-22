'use client';

import { KeyRound, MailCheck, Save, Send, ShieldCheck, Trash2 } from 'lucide-react';
import { useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { Button } from '../../../components/ui/button';
import { useToast } from '../../../components/ui/feedback';
import { Select } from '../../../components/ui/select';
import { KindleSendQueuePage } from '../../kindle/kindle-send-queue-page';
import { SettingsCenterShell } from './settings-center-shell';
import { SettingsTabs } from './settings-tabs';

type EmailSettings = {
  smtp: {
    host: string;
    port: number;
    security: 'starttls' | 'ssl' | 'none';
    username: string;
    fromEmail: string;
    fromName: string;
    maxAttachmentMb: number | null;
    passwordConfigured: boolean;
  };
  kindle: { email: string };
};

type EmailSettingsPayload = { ok: boolean; data?: EmailSettings; error?: { message: string } };

const emptySettings: EmailSettings = {
  smtp: { host: '', port: 587, security: 'starttls', username: '', fromEmail: '', fromName: '二毛图书', maxAttachmentMb: null, passwordConfigured: false },
  kindle: { email: '' }
};

const securityOptions = [
  { value: 'starttls', label: 'STARTTLS' },
  { value: 'ssl', label: 'SSL/TLS' },
  { value: 'none', label: '不加密' }
];

function inputClassName() {
  return 'mt-2 h-11 w-full rounded-xl border border-[#DCD7D1] bg-white px-4 text-sm text-[#2B2926] outline-none transition focus:border-[#EF8B73] focus:ring-4 focus:ring-[#FAD9D0]/70';
}

export function EmailSettingsPage() {
  const searchParams = useSearchParams();
  const requested = searchParams.get('tab');
  const active = requested === 'kindle' || requested === 'queue' ? requested : 'smtp';
  const toast = useToast();
  const [settings, setSettings] = useState<EmailSettings>(emptySettings);
  const [smtp, setSmtp] = useState({ ...emptySettings.smtp, password: '' });
  const [kindleEmail, setKindleEmail] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [clearPassword, setClearPassword] = useState(false);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/email-settings', { cache: 'no-store' });
      const payload = (await response.json()) as EmailSettingsPayload;
      if (!payload.ok || !payload.data) throw new Error(payload.error?.message ?? '读取邮件设置失败');
      setSettings(payload.data);
      setSmtp({ ...payload.data.smtp, password: '' });
      setKindleEmail(payload.data.kindle.email);
      setClearPassword(false);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取邮件设置失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadSettings(); }, [loadSettings]);

  async function saveSmtp() {
    setBusy('save-smtp');
    try {
      const body: Record<string, unknown> = {
        smtp: {
          host: smtp.host,
          port: smtp.port,
          security: smtp.security,
          username: smtp.username,
          fromEmail: smtp.fromEmail,
          fromName: smtp.fromName,
          maxAttachmentMb: smtp.maxAttachmentMb
        },
        clearSmtpPassword: clearPassword
      };
      if (smtp.password.trim()) (body.smtp as Record<string, unknown>).password = smtp.password;
      const response = await fetch('/api/email-settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const payload = (await response.json()) as EmailSettingsPayload;
      if (!payload.ok || !payload.data) throw new Error(payload.error?.message ?? '保存 SMTP 设置失败');
      toast.success('SMTP 设置已保存');
      await loadSettings();
    } catch (reason) {
      toast.error('保存失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setBusy('');
    }
  }

  async function testConnection() {
    setBusy('test-smtp');
    try {
      const response = await fetch('/api/email-settings/smtp-test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ smtp: { ...smtp, password: smtp.password || undefined }, clearSmtpPassword: clearPassword })
      });
      const payload = (await response.json()) as { ok: boolean; data?: { message: string }; error?: { message: string } };
      if (!payload.ok) throw new Error(payload.error?.message ?? 'SMTP 连接失败');
      toast.success('SMTP 测试成功', payload.data?.message);
    } catch (reason) {
      toast.error('SMTP 测试失败', reason instanceof Error ? reason.message : '请检查服务器设置');
    } finally {
      setBusy('');
    }
  }

  async function saveKindle() {
    setBusy('save-kindle');
    try {
      const response = await fetch('/api/email-settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kindle: { email: kindleEmail } }) });
      const payload = (await response.json()) as EmailSettingsPayload;
      if (!payload.ok || !payload.data) throw new Error(payload.error?.message ?? '保存 Kindle 邮箱失败');
      setSettings(payload.data);
      toast.success('Kindle 邮箱已保存');
    } catch (reason) {
      toast.error('保存失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setBusy('');
    }
  }

  return (
    <SettingsCenterShell title="邮件与 Kindle" description="配置 SMTP 发件服务、Kindle 收件邮箱并查看图书发送状态。">
      <SettingsTabs active={active} tabs={[
        { key: 'smtp', label: 'SMTP 设置', href: '/settings/email?tab=smtp' },
        { key: 'kindle', label: 'Kindle 设置', href: '/settings/email?tab=kindle' },
        { key: 'queue', label: '发送队列', href: '/settings/email?tab=queue' }
      ]} />
      <div className="mt-6">
        {error ? <div className="mb-5 rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
        {active === 'smtp' ? (
          <section className="max-w-4xl rounded-[26px] border border-[#E2DDD7] bg-white p-5 shadow-sm shadow-stone-900/[0.03] sm:p-6">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#FFF0EA] text-[#DD4729]"><MailCheck size={19} /></span>
              <div><h3 className="text-lg font-semibold text-[#292724]">SMTP 发件服务</h3><p className="mt-1 text-sm leading-6 text-[#77716A]">支持 STARTTLS、SSL/TLS 和不加密连接。测试连接不会发送邮件。</p></div>
            </div>
            <div className="mt-6 grid gap-5 md:grid-cols-2">
              <label className="text-sm font-medium text-[#5E5953]">SMTP 主机<input disabled={loading} value={smtp.host} onChange={(event) => setSmtp({ ...smtp, host: event.target.value })} placeholder="smtp.example.com" className={inputClassName()} /></label>
              <label className="text-sm font-medium text-[#5E5953]">端口<input disabled={loading} type="number" min={1} max={65535} value={smtp.port} onChange={(event) => setSmtp({ ...smtp, port: Number(event.target.value) })} className={inputClassName()} /></label>
              <div className="text-sm font-medium text-[#5E5953]">
                <div>安全模式</div>
                <Select
                  disabled={loading}
                  value={smtp.security}
                  options={securityOptions}
                  onChange={(security) => setSmtp({ ...smtp, security })}
                  ariaLabel="SMTP 安全模式"
                  className="mt-2 w-full"
                  triggerClassName="h-11"
                />
              </div>
              <label className="text-sm font-medium text-[#5E5953]">附件大小上限（MB，可选）<input disabled={loading} type="number" min={1} max={1000} value={smtp.maxAttachmentMb ?? ''} onChange={(event) => setSmtp({ ...smtp, maxAttachmentMb: event.target.value ? Number(event.target.value) : null })} placeholder="留空则由邮件服务商限制" className={inputClassName()} /></label>
              <label className="text-sm font-medium text-[#5E5953]">SMTP 用户名<input disabled={loading} value={smtp.username} onChange={(event) => setSmtp({ ...smtp, username: event.target.value })} autoComplete="username" placeholder="无需认证时留空" className={inputClassName()} /></label>
              <label className="text-sm font-medium text-[#5E5953]">SMTP 密码<input disabled={loading || clearPassword} value={smtp.password} onChange={(event) => { setSmtp({ ...smtp, password: event.target.value }); setClearPassword(false); }} type="password" autoComplete="new-password" placeholder={settings.smtp.passwordConfigured ? '已配置，留空表示不修改' : '无需认证时留空'} className={inputClassName()} /></label>
              <label className="text-sm font-medium text-[#5E5953]">发件邮箱<input disabled={loading} value={smtp.fromEmail} onChange={(event) => setSmtp({ ...smtp, fromEmail: event.target.value })} type="email" placeholder="reader@example.com" className={inputClassName()} /></label>
              <label className="text-sm font-medium text-[#5E5953]">发件名称<input disabled={loading} value={smtp.fromName} onChange={(event) => setSmtp({ ...smtp, fromName: event.target.value })} placeholder="二毛图书" className={inputClassName()} /></label>
            </div>
            {settings.smtp.passwordConfigured ? (
              <button type="button" onClick={() => { setClearPassword((value) => !value); setSmtp({ ...smtp, password: '' }); }} className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-[#A34A36] hover:text-[#D94322]"><Trash2 size={15} />{clearPassword ? '取消清除 SMTP 密码' : '保存时清除 SMTP 密码'}</button>
            ) : null}
            {smtp.security === 'none' ? <div className="mt-5 flex items-start gap-2 rounded-2xl bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-700"><ShieldCheck size={17} className="mt-0.5 shrink-0" />当前连接不会加密，仅应在可信内网邮件服务器中使用。</div> : null}
            <div className="mt-6 flex flex-wrap justify-end gap-3">
              <Button variant="secondary" icon={KeyRound} loading={busy === 'test-smtp'} loadingText="测试中" onClick={() => void testConnection()}>测试连接</Button>
              <Button icon={Save} loading={busy === 'save-smtp'} loadingText="保存中" onClick={() => void saveSmtp()}>保存 SMTP</Button>
            </div>
          </section>
        ) : active === 'kindle' ? (
          <section className="max-w-3xl rounded-[26px] border border-[#E2DDD7] bg-white p-5 shadow-sm shadow-stone-900/[0.03] sm:p-6">
            <div className="flex items-start gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#FFF0EA] text-[#DD4729]"><Send size={19} /></span><div><h3 className="text-lg font-semibold text-[#292724]">Kindle 收件邮箱</h3><p className="mt-1 text-sm leading-6 text-[#77716A]">图书会以单个 EPUB 或 PDF 附件发送到这个地址。</p></div></div>
            <label className="mt-6 block text-sm font-medium text-[#5E5953]">Kindle 邮箱<input disabled={loading} value={kindleEmail} onChange={(event) => setKindleEmail(event.target.value)} type="email" placeholder="name_123@kindle.com" className={inputClassName()} /></label>
            <div className="mt-5 rounded-2xl bg-[#F8F6F3] px-4 py-3 text-sm leading-6 text-[#706A63]">当前发件地址：<span className="font-medium text-[#3F3B37]">{settings.smtp.fromEmail || '尚未配置'}</span>。请确保该地址可以向你的 Kindle 邮箱发送个人文档。</div>
            <div className="mt-6 flex justify-end"><Button icon={Save} loading={busy === 'save-kindle'} loadingText="保存中" onClick={() => void saveKindle()}>保存 Kindle 邮箱</Button></div>
          </section>
        ) : <KindleSendQueuePage embedded />}
      </div>
    </SettingsCenterShell>
  );
}

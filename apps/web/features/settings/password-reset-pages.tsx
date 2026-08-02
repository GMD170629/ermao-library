'use client';

import { ArrowLeft, FileKey2, LockKeyhole } from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';
import { FormEvent, ReactNode, useEffect, useState } from 'react';
import { Button } from '../../components/ui/button';
import { withBasePath } from '../../lib/base-path';
import { PRODUCT_NAME } from '../../lib/brand';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type ApiPayload = {
  ok: boolean;
  data?: { message?: string; filePath?: string };
  error?: { message?: string };
};

const inputClassName = 'mt-2 h-12 w-full rounded-[12px] border border-[#DED8D1] bg-white px-4 text-sm text-[#17191D] outline-none transition placeholder:text-[#AAA39C] focus:border-[#ED9D86] focus:ring-4 focus:ring-[#FFE4DC]';

function AuthCard({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <div className="shuku-auth-safe-screen flex min-h-screen items-center justify-center bg-[#F4F1ED] p-6 sm:p-8">
      <main className="w-full max-w-[430px] rounded-[24px] border border-[#E2DDD6] bg-[#FFFDFA] p-8 shadow-[0_24px_70px_rgba(62,48,38,0.10)] sm:p-10">
        <div className="mx-auto h-14 w-14 overflow-hidden rounded-[15px] bg-[#F7F1E8] shadow-sm">
          <Image src={withBasePath('/icons/icon-192.png')} alt="" width={56} height={56} className="h-full w-full object-cover" priority />
        </div>
        <h1 className="mt-6 text-center text-[28px] font-semibold tracking-[-0.035em] text-[#17191D]">{title}</h1>
        <p className="mt-2 text-center text-sm leading-6 text-[#77736F]">{description}</p>
        {children}
      </main>
    </div>
  );
}

export function ForgotPasswordPage() {
  const { t: i18nAttribute } = useAttributeI18n();
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch('/api/auth/password-reset/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim() })
      });
      const payload = (await response.json()) as ApiPayload;
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '创建密码重置文件失败');
      const path = payload.data?.filePath;
      setMessage(path ? `${payload.data?.message ?? '密码重置文件已创建'} 文件位置：${path}` : (payload.data?.message ?? '密码重置文件已创建。'));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '创建密码重置文件失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthCard title={i18nAttribute("重置密码")} description={i18nAttribute("输入你在{value0}中使用的登录邮箱。", { value0: PRODUCT_NAME })}>
      <form onSubmit={submit} className="mt-8">
        <label className="block text-sm font-medium text-[#4F4B47]">
          <I18nText>登录邮箱</I18nText><input type="email" required autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" className={inputClassName} />
        </label>
        {message ? <div className="mt-4 rounded-[12px] border border-emerald-100 bg-emerald-50 px-4 py-3 text-sm leading-6 text-emerald-800">{message}</div> : null}
        {error ? <div className="mt-4 rounded-[12px] border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
        <Button className="mt-5 h-12 w-full rounded-[12px]" icon={FileKey2} loading={loading} loadingText={i18nAttribute("创建中")}>
          <I18nText>创建密码重置文件</I18nText></Button>
      </form>
      <Link href="/login" className="mt-6 flex items-center justify-center gap-2 text-sm text-[#6F6A65] transition hover:text-[#D94A2B]">
        <ArrowLeft size={15} /><I18nText>返回登录</I18nText></Link>
    </AuthCard>
  );
}

export function ResetPasswordPage() {
  const { t: i18nAttribute } = useAttributeI18n();
  const [token, setToken] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const raw = window.location.hash.replace(/^#token=/, '').replace(/^#/, '');
    if (!raw) return;
    try {
      setToken(decodeURIComponent(raw));
    } catch {
      setError('重置链接无效');
    }
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    if (!token) {
      setError('重置链接无效，请重新申请');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致');
      return;
    }
    if (newPassword.length < 10) {
      setError('新密码至少需要 10 个字符');
      return;
    }
    setLoading(true);
    try {
      const response = await fetch('/api/auth/password-reset/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, newPassword })
      });
      const payload = (await response.json()) as ApiPayload;
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '重置密码失败');
      window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
      setToken('');
      setComplete(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '重置密码失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthCard title={complete ? i18nAttribute("密码已重置") : i18nAttribute("设置新密码")} description={complete ? i18nAttribute("现在可以使用新密码登录。") : i18nAttribute("新密码至少需要 10 个字符，链接仅能使用一次。")}>
      {complete ? (
        <Link href="/login" className="mt-8 inline-flex h-12 w-full items-center justify-center rounded-[12px] bg-[#FF4F2A] px-4 text-sm font-medium text-white transition hover:bg-[#E94320]">
          <I18nText>返回登录</I18nText></Link>
      ) : (
        <form onSubmit={submit} className="mt-8 space-y-4">
          <label className="block text-sm font-medium text-[#4F4B47]">
            <I18nText>新密码</I18nText><input type="password" required minLength={10} maxLength={128} autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className={inputClassName} />
          </label>
          <label className="block text-sm font-medium text-[#4F4B47]">
            <I18nText>再次输入新密码</I18nText><input type="password" required minLength={10} maxLength={128} autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} className={inputClassName} />
          </label>
          {!token && !error ? <div className="rounded-[12px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"><I18nText>重置链接缺少令牌，请重新申请。</I18nText></div> : null}
          {error ? <div className="rounded-[12px] border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
          <Button className="h-12 w-full rounded-[12px]" icon={LockKeyhole} loading={loading} loadingText={i18nAttribute("重置中")} disabled={!token}>
            <I18nText>重置密码</I18nText></Button>
        </form>
      )}
      {!complete ? (
        <Link href="/login" className="mt-6 flex items-center justify-center gap-2 text-sm text-[#6F6A65] transition hover:text-[#D94A2B]">
          <ArrowLeft size={15} /><I18nText>返回登录</I18nText></Link>
      ) : null}
    </AuthCard>
  );
}

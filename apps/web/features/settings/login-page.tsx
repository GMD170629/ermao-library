'use client';

import { AlertCircle, Loader2, Lock } from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { FormEvent, useEffect, useState } from 'react';
import { Button } from '../../components/ui/button';
import { safePostLoginPath } from '../../lib/auth-routes';
import { withBasePath } from '../../lib/base-path';
import { PRODUCT_NAME, PRODUCT_TAGLINE } from '../../lib/brand';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type LoginPayload = { ok: boolean; error?: { message?: string; details?: { code?: string } } };
type SetupStatusPayload = { ok: boolean; data?: { initialized?: boolean } };

async function readLoginPayload(response: Response): Promise<LoginPayload> {
  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes('application/json')) {
    return (await response.json()) as LoginPayload;
  }
  const text = await response.text().catch(() => '');
  return {
    ok: false,
    error: {
      message: response.status >= 500
        ? '登录服务暂时不可用，请确认 Python API 已启动。'
        : text.trim() || `登录失败（HTTP ${response.status}）`
    }
  };
}

export function LoginPage() {
  const { t: i18nAttribute } = useAttributeI18n();
  const router = useRouter();
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [checkingSetup, setCheckingSetup] = useState(true);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    fetch('/api/auth/setup/status', {
      cache: 'no-store',
      credentials: 'same-origin',
      signal: controller.signal
    })
      .then(async (response) => {
        const payload = await response.json().catch(() => null) as SetupStatusPayload | null;
        if (!active) return;
        if (response.ok && payload?.ok && payload.data?.initialized === false) {
          router.replace('/setup');
          return;
        }
        setCheckingSetup(false);
      })
      .catch((reason) => {
        if (active && !(reason instanceof DOMException && reason.name === 'AbortError')) setCheckingSetup(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [router]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedEmail = login.trim();
    if (!normalizedEmail) {
      setError('请输入登录邮箱');
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) {
      setError('请输入有效的邮箱地址');
      return;
    }
    if (!password) {
      setError('请输入登录密码');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: normalizedEmail, password })
      });
      const payload = await readLoginPayload(response);
      if (response.status === 409 && payload.error?.details?.code === 'SETUP_REQUIRED') {
        router.replace('/setup');
        return;
      }
      if (!response.ok || !payload.ok) {
        setError(response.status === 401 ? '邮箱或密码不正确' : (payload.error?.message ?? '登录失败'));
        return;
      }
      const next = new URLSearchParams(window.location.search).get('next');
      router.replace(safePostLoginPath(next));
      router.refresh();
    } catch {
      setError('无法连接登录服务，请确认 Web 和 Python API 都已启动。');
    } finally {
      setLoading(false);
    }
  }

  if (checkingSetup) {
    return (
      <div className="shuku-auth-safe-screen flex min-h-screen items-center justify-center bg-[#f4f1ed] p-6 sm:p-8" role="status" aria-live="polite">
        <div className="flex w-full max-w-[430px] flex-col items-center rounded-[24px] border border-[#e2ddd6] bg-[#fffdfa] px-8 py-16 text-center shadow-[0_24px_70px_rgba(62,48,38,0.10)]">
          <Loader2 size={26} className="animate-spin text-[#D94A2B]" />
          <p className="mt-5 text-sm text-[#77736f]"><I18nText>正在检查系统状态...</I18nText></p>
        </div>
      </div>
    );
  }

  return (
    <div className="shuku-auth-safe-screen flex min-h-screen items-center justify-center bg-[#f4f1ed] p-6 sm:p-8">
      <form onSubmit={submit} noValidate className="w-full max-w-[430px] rounded-[24px] border border-[#e2ddd6] bg-[#fffdfa] p-8 shadow-[0_24px_70px_rgba(62,48,38,0.10)] sm:p-10">
        <div className="mx-auto h-14 w-14 overflow-hidden rounded-[15px] bg-[#F7F1E8] shadow-sm">
          <Image src={withBasePath('/icons/icon-192.png')} alt="" width={56} height={56} className="h-full w-full object-cover" priority />
        </div>
        <h1 className="mt-6 text-center text-[28px] font-semibold tracking-[-0.035em] text-[#17191d]">{i18nAttribute('欢迎回到{value0}', { value0: i18nAttribute(PRODUCT_NAME) })}</h1>
        <p className="mt-2 text-center text-sm text-[#77736f]">{PRODUCT_TAGLINE}</p>
        <div className="mt-8 space-y-4">
          <label className="block">
            <span className="text-sm font-medium text-[#4f4b47]"><I18nText>邮箱</I18nText></span>
            <input type="email" required value={login} onChange={(event) => { setLogin(event.target.value); setError(''); }} autoComplete="username" placeholder="name@example.com" className="mt-2 h-12 w-full rounded-[12px] border border-[#ded8d1] bg-white px-4 text-sm text-[#17191d] outline-none transition placeholder:text-[#aaa39c] focus:border-[#ed9d86] focus:ring-4 focus:ring-[#ffe4dc]" />
          </label>
          <label className="block">
            <span className="flex items-center justify-between gap-3 text-sm font-medium text-[#4f4b47]">
              <I18nText>密码</I18nText><Link href="/forgot-password" className="font-normal text-[#D94A2B] transition hover:text-[#B93B20]"><I18nText>忘记密码？</I18nText></Link>
            </span>
            <input type="password" required maxLength={128} value={password} onChange={(event) => { setPassword(event.target.value); setError(''); }} autoComplete="current-password" placeholder={i18nAttribute("输入登录密码")} className="mt-2 h-12 w-full rounded-[12px] border border-[#ded8d1] bg-white px-4 text-sm text-[#17191d] outline-none transition placeholder:text-[#aaa39c] focus:border-[#ed9d86] focus:ring-4 focus:ring-[#ffe4dc]" />
          </label>
          {error ? <div role="alert" className="flex items-start gap-2 rounded-[12px] border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700"><AlertCircle size={17} className="mt-0.5 shrink-0" /><span>{error}</span></div> : null}
          <Button className="h-12 w-full rounded-[12px]" loading={loading} loadingText={i18nAttribute("登录中")}><I18nText>登录</I18nText></Button>
        </div>
        <div className="mt-7 flex items-center justify-center gap-2 text-xs text-[#8d8781]">
          <Lock size={14} strokeWidth={1.8} />
          <span><I18nText>私有部署 · 数据保留在你的服务器</I18nText></span>
        </div>
      </form>
    </div>
  );
}

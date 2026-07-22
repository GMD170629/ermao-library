'use client';

import { AlertCircle, ArrowRight, Check, Database, Loader2, ShieldCheck, UserRoundPlus } from 'lucide-react';
import Image from 'next/image';
import { useRouter } from 'next/navigation';
import { FormEvent, useCallback, useEffect, useState } from 'react';
import { withBasePath } from '../../lib/base-path';
import { PRODUCT_NAME } from '../../lib/brand';

type SetupStage = 'checking' | 'ready' | 'submitting' | 'complete' | 'unavailable';
type SetupPayload = {
  ok: boolean;
  data?: { initialized?: boolean; user?: { email?: string; name?: string } };
  error?: { message?: string };
  detail?: Array<{ loc?: Array<string | number>; msg?: string }>;
};

async function readSetupPayload(response: Response): Promise<SetupPayload> {
  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes('application/json')) {
    const payload = await response.json() as SetupPayload;
    if (!payload.error?.message && payload.detail?.length) {
      const passwordError = payload.detail.find((item) => item.loc?.includes('password'));
      return {
        ...payload,
        error: { message: passwordError ? '密码格式不正确，请至少输入 10 位' : '账户信息格式不正确，请检查后重试' }
      };
    }
    return payload;
  }
  const message = await response.text().catch(() => '');
  return { ok: false, error: { message: message.trim() || `请求失败（HTTP ${response.status}）` } };
}

export function SetupPage() {
  const router = useRouter();
  const [stage, setStage] = useState<SetupStage>('checking');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');

  const checkStatus = useCallback(async (signal?: AbortSignal) => {
    setStage('checking');
    setError('');
    try {
      const response = await fetch('/api/auth/setup/status', {
        cache: 'no-store',
        credentials: 'same-origin',
        signal
      });
      const payload = await readSetupPayload(response);
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '无法检查系统状态');
      if (!payload.data?.initialized) {
        setStage('ready');
        return;
      }

      const session = await fetch('/api/auth/me', {
        cache: 'no-store',
        credentials: 'same-origin',
        signal
      });
      router.replace(session.ok ? '/library' : '/login');
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') return;
      setError(reason instanceof Error ? reason.message : '无法连接初始化服务');
      setStage('unavailable');
    }
  }, [router]);

  useEffect(() => {
    const controller = new AbortController();
    void checkStatus(controller.signal);
    return () => controller.abort();
  }, [checkStatus]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedEmail = email.trim();
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
    if (password.length < 10) {
      setError('密码至少需要 10 位');
      return;
    }
    if (!confirmPassword) {
      setError('请再次输入登录密码');
      return;
    }
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致');
      return;
    }

    setStage('submitting');
    setError('');
    try {
      const response = await fetch('/api/auth/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        // Keep the legacy API field during rolling upgrades; it is intentionally not user-configurable.
        body: JSON.stringify({ name: '管理员', email: normalizedEmail, password })
      });
      const payload = await readSetupPayload(response);
      if (response.status === 409) {
        router.replace('/login');
        return;
      }
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '账户创建失败');
      setEmail(payload.data?.user?.email ?? normalizedEmail);
      setStage('complete');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法连接初始化服务');
      setStage('ready');
    }
  }

  const statusChecked = stage !== 'checking' && stage !== 'unavailable';
  const accountCreated = stage === 'complete';

  return (
    <main
      data-testid="setup-page"
      className="shuku-auth-safe-screen flex min-h-[100dvh] items-center justify-center bg-[#E8DCC7] p-6 text-[#606C38] sm:p-8"
      style={{ fontFamily: '"Avenir Next", "PingFang SC", sans-serif' }}
    >
      <section className="grid w-full max-w-[1040px] overflow-hidden rounded-[32px] border border-[#B08B6E]/40 bg-[#D4B895] shadow-[0_30px_90px_rgba(96,108,56,0.16)] lg:grid-cols-[minmax(0,1.25fr)_minmax(300px,0.75fr)]">
        <div className="p-7 sm:p-10 lg:p-14">
          <div className="flex items-center gap-3">
            <span className="h-12 w-12 overflow-hidden rounded-2xl bg-[#E8DCC7] shadow-sm">
              <Image src={withBasePath('/icons/icon-192.png')} alt="" width={48} height={48} className="h-full w-full object-cover" priority />
            </span>
            <div>
              <div className="text-sm font-semibold text-[#C66B3D]">{PRODUCT_NAME}</div>
              <div className="mt-0.5 text-xs text-[#606C38]/70">首次启动设置</div>
            </div>
          </div>

          {stage === 'checking' ? (
            <div className="flex min-h-[430px] flex-col items-center justify-center text-center" role="status" aria-live="polite">
              <Loader2 className="animate-spin text-[#C66B3D]" size={30} />
              <h1 className="mt-6 text-2xl font-semibold tracking-[-0.03em]">正在检查系统状态</h1>
              <p className="mt-2 text-sm text-[#606C38]/70">确认是否需要创建第一个管理账户</p>
            </div>
          ) : stage === 'unavailable' ? (
            <div className="flex min-h-[430px] flex-col items-start justify-center">
              <h1 className="text-3xl font-semibold tracking-[-0.04em]">暂时无法开始设置</h1>
              <p className="mt-4 max-w-md text-sm leading-7 text-[#606C38]/80">{error}</p>
              <button type="button" onClick={() => void checkStatus()} className="mt-7 inline-flex min-h-12 items-center justify-center rounded-2xl bg-[#C66B3D] px-6 text-sm font-semibold text-[#E8DCC7] transition hover:bg-[#B08B6E] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#8B9D83]/40">
                重新检查
              </button>
            </div>
          ) : stage === 'complete' ? (
            <div className="flex min-h-[430px] flex-col items-start justify-center" aria-live="polite">
              <span className="flex h-14 w-14 items-center justify-center rounded-[20px] bg-[#8B9D83] text-[#E8DCC7]"><Check size={28} strokeWidth={2.4} /></span>
              <h1 className="mt-7 text-3xl font-semibold tracking-[-0.04em] sm:text-4xl">你的私人书库已准备好</h1>
              <p className="mt-4 text-sm leading-7 text-[#606C38]/80">管理账户 {email} 已创建并登录，现在可以添加书库目录或上传第一本读物。</p>
              <button type="button" onClick={() => { router.replace('/library'); router.refresh(); }} className="mt-8 inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl bg-[#C66B3D] px-6 text-sm font-semibold text-[#E8DCC7] transition hover:bg-[#B08B6E] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#8B9D83]/40">
                进入书库 <ArrowRight size={17} />
              </button>
            </div>
          ) : (
            <>
              <div className="mt-10 max-w-xl">
                <h1 className="text-3xl font-semibold tracking-[-0.045em] sm:text-4xl">创建你的管理账户</h1>
                <p className="mt-3 text-sm leading-7 text-[#606C38]/80">该账户用于登录和管理这套私人图书馆。创建后，系统不会再开放初始化入口。</p>
              </div>

              <form data-testid="setup-form" onSubmit={submit} noValidate className="mt-8 space-y-4">
                <label className="block">
                  <span className="text-sm font-semibold">登录邮箱</span>
                  <input autoFocus type="email" required maxLength={191} value={email} onChange={(event) => { setEmail(event.target.value); setError(''); }} autoComplete="username" placeholder="name@example.com" className="mt-2 h-12 w-full rounded-2xl border border-[#B08B6E]/55 bg-[#E8DCC7] px-4 text-sm text-[#606C38] outline-none transition placeholder:text-[#8B9D83] focus:border-[#C66B3D] focus:ring-4 focus:ring-[#C66B3D]/15" />
                </label>
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="block">
                    <span className="text-sm font-semibold">登录密码</span>
                    <input type="password" required minLength={10} maxLength={128} value={password} onChange={(event) => { setPassword(event.target.value); setError(''); }} autoComplete="new-password" placeholder="至少 10 位" className="mt-2 h-12 w-full rounded-2xl border border-[#B08B6E]/55 bg-[#E8DCC7] px-4 text-sm text-[#606C38] outline-none transition placeholder:text-[#8B9D83] focus:border-[#C66B3D] focus:ring-4 focus:ring-[#C66B3D]/15" />
                  </label>
                  <label className="block">
                    <span className="text-sm font-semibold">确认密码</span>
                    <input type="password" required minLength={10} maxLength={128} value={confirmPassword} onChange={(event) => { setConfirmPassword(event.target.value); setError(''); }} autoComplete="new-password" placeholder="再次输入密码" className="mt-2 h-12 w-full rounded-2xl border border-[#B08B6E]/55 bg-[#E8DCC7] px-4 text-sm text-[#606C38] outline-none transition placeholder:text-[#8B9D83] focus:border-[#C66B3D] focus:ring-4 focus:ring-[#C66B3D]/15" />
                  </label>
                </div>
                {error ? <div role="alert" className="flex items-start gap-2 rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700"><AlertCircle size={17} className="mt-0.5 shrink-0" /><span>{error}</span></div> : null}
                <button type="submit" disabled={stage === 'submitting'} className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl bg-[#C66B3D] px-6 text-sm font-semibold text-[#E8DCC7] transition hover:bg-[#B08B6E] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#8B9D83]/40 disabled:cursor-not-allowed disabled:opacity-70">
                  {stage === 'submitting' ? <><Loader2 size={17} className="animate-spin" /> 正在创建账户</> : <>创建账户 <ArrowRight size={17} /></>}
                </button>
              </form>
            </>
          )}
        </div>

        <aside className="bg-[#606C38] p-7 text-[#E8DCC7] sm:p-10 lg:p-12">
          <div className="flex h-full flex-col">
            <ShieldCheck size={28} strokeWidth={1.8} />
            <h2 className="mt-6 text-xl font-semibold tracking-[-0.03em]">初始化清单</h2>
            <ol className="mt-8 space-y-6">
              <SetupStep icon={Database} title="检查系统状态" description="确认数据库和存储目录可用" complete={statusChecked} active={stage === 'checking' || stage === 'unavailable'} />
              <SetupStep icon={UserRoundPlus} title="创建管理账户" description="设置邮箱和登录密码" complete={accountCreated} active={stage === 'ready' || stage === 'submitting'} />
              <SetupStep icon={ArrowRight} title="进入私人书库" description="添加目录或上传本地读物" complete={false} active={stage === 'complete'} />
            </ol>
            <p className="mt-auto pt-10 text-xs leading-6 text-[#E8DCC7]/70">账号信息仅保存在你的服务器中。以后可以在设置页面修改邮箱、密码和头像。</p>
          </div>
        </aside>
      </section>
    </main>
  );
}

function SetupStep({ icon: Icon, title, description, complete, active }: { icon: typeof Database; title: string; description: string; complete: boolean; active: boolean }) {
  return (
    <li className="flex gap-4">
      <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl ${complete ? 'bg-[#8B9D83]' : active ? 'bg-[#C66B3D]' : 'bg-[#8B9D83]/25'}`}>
        {complete ? <Check size={18} strokeWidth={2.5} /> : <Icon size={18} strokeWidth={1.9} />}
      </span>
      <span className="pt-0.5">
        <span className="block text-sm font-semibold">{title}</span>
        <span className="mt-1 block text-xs leading-5 text-[#E8DCC7]/65">{description}</span>
      </span>
    </li>
  );
}

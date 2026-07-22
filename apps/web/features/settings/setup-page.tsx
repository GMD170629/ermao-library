'use client';

import { AlertCircle, ArrowRight, Check, Database, FolderPlus, Loader2, ShieldCheck, UserRoundPlus } from 'lucide-react';
import Image from 'next/image';
import { useRouter } from 'next/navigation';
import { FormEvent, useCallback, useEffect, useState } from 'react';
import { withBasePath } from '../../lib/base-path';
import { PRODUCT_NAME } from '../../lib/brand';

type SetupStage = 'checking' | 'account' | 'creating-account' | 'folder' | 'saving-folder' | 'complete' | 'unavailable';
type SetupPayload = {
  ok: boolean;
  data?: { initialized?: boolean; user?: { email?: string; name?: string } };
  error?: { message?: string };
  detail?: Array<{ loc?: Array<string | number>; msg?: string }>;
};

const setupProgressKey = 'shuku.setup.progress';

type SetupProgress = {
  stage: 'folder' | 'complete' | 'import';
  email: string;
  folderAdded: boolean;
  folderPath: string;
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
  const [folderName, setFolderName] = useState('我的书库');
  const [folderPath, setFolderPath] = useState('/books');
  const [folderAdded, setFolderAdded] = useState(false);
  const [error, setError] = useState('');

  function saveProgress(progress: SetupProgress) {
    window.localStorage.setItem(setupProgressKey, JSON.stringify(progress));
  }

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
        setStage('account');
        return;
      }

      const session = await fetch('/api/auth/me', {
        cache: 'no-store',
        credentials: 'same-origin',
        signal
      });
      if (session.ok) {
        try {
          const saved = JSON.parse(window.localStorage.getItem(setupProgressKey) ?? 'null') as SetupProgress | null;
          if (saved && ['folder', 'import', 'complete'].includes(saved.stage)) {
            setEmail(saved.email);
            setFolderAdded(saved.folderAdded);
            setFolderPath(saved.folderPath || '/books');
            // Older in-progress sessions may still contain the removed import step.
            setStage(saved.stage === 'folder' ? 'folder' : 'complete');
            return;
          }
        } catch {
          window.localStorage.removeItem(setupProgressKey);
        }
      }
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

    setStage('creating-account');
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
      const accountEmail = payload.data?.user?.email ?? normalizedEmail;
      setEmail(accountEmail);
      setStage('folder');
      saveProgress({ stage: 'folder', email: accountEmail, folderAdded: false, folderPath });
      void fetch('/api/monitor-folders', { cache: 'no-store' })
        .then((result) => result.json())
        .then((result: { ok?: boolean; data?: { monitorRoot?: string | null } }) => {
          if (result.ok && result.data?.monitorRoot) {
            setFolderPath(result.data.monitorRoot);
            saveProgress({ stage: 'folder', email: accountEmail, folderAdded: false, folderPath: result.data.monitorRoot });
          }
        })
        .catch(() => undefined);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法连接初始化服务');
      setStage('account');
    }
  }

  async function saveFolder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!folderPath.trim()) {
      setError('请输入监控文件夹路径');
      return;
    }
    setStage('saving-folder');
    setError('');
    try {
      const response = await fetch('/api/monitor-folders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          name: folderName.trim() || '我的书库',
          rootPath: folderPath.trim(),
          enabled: true,
          ignorePatterns: '',
          ignoreHidden: true,
          minFileSizeBytes: 0
        })
      });
      const payload = await readSetupPayload(response);
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '监控文件夹添加失败');
      setFolderAdded(true);
      setStage('complete');
      saveProgress({ stage: 'complete', email, folderAdded: true, folderPath: folderPath.trim() });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '监控文件夹添加失败');
      setStage('folder');
    }
  }

  const statusChecked = stage !== 'checking' && stage !== 'unavailable';
  const accountCreated = !['checking', 'account', 'creating-account', 'unavailable'].includes(stage);
  const folderActive = stage === 'folder' || stage === 'saving-folder';

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
              <p className="mt-4 text-sm leading-7 text-[#606C38]/80">管理账户 {email} 已创建并登录。{folderAdded ? '监控文件夹已启用，系统会自动识别目录中已有和以后新增的读物。' : '你可以稍后在设置中添加监控文件夹。'}</p>
              <button type="button" onClick={() => { window.localStorage.removeItem(setupProgressKey); router.replace('/library'); router.refresh(); }} className="mt-8 inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl bg-[#C66B3D] px-6 text-sm font-semibold text-[#E8DCC7] transition hover:bg-[#B08B6E] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#8B9D83]/40">
                进入书库 <ArrowRight size={17} />
              </button>
            </div>
          ) : stage === 'folder' || stage === 'saving-folder' ? (
            <>
              <div className="mt-10 max-w-xl">
                <div className="text-sm font-semibold text-[#C66B3D]">第 2 步，共 2 步</div>
                <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] sm:text-4xl">添加监控文件夹</h1>
                <p className="mt-3 text-sm leading-7 text-[#606C38]/80">把服务器或 NAS 上的读物目录加入监控。目录内已有和以后新增的支持格式都会由后台自动识别。</p>
              </div>
              <form onSubmit={saveFolder} className="mt-8 space-y-4">
                <label className="block">
                  <span className="text-sm font-semibold">文件夹名称</span>
                  <input value={folderName} onChange={(event) => { setFolderName(event.target.value); setError(''); }} maxLength={100} className="mt-2 h-12 w-full rounded-2xl border border-[#B08B6E]/55 bg-[#E8DCC7] px-4 text-sm outline-none transition focus:border-[#C66B3D] focus:ring-4 focus:ring-[#C66B3D]/15" />
                </label>
                <label className="block">
                  <span className="text-sm font-semibold">监控文件夹路径</span>
                  <input value={folderPath} onChange={(event) => { setFolderPath(event.target.value); setError(''); }} placeholder="/monitor" className="mt-2 h-12 w-full rounded-2xl border border-[#B08B6E]/55 bg-[#E8DCC7] px-4 text-sm outline-none transition placeholder:text-[#8B9D83] focus:border-[#C66B3D] focus:ring-4 focus:ring-[#C66B3D]/15" />
                  <span className="mt-2 block text-xs leading-5 text-[#606C38]/65">路径必须位于应用可访问的监控根目录内；Docker 部署通常为 /monitor。</span>
                </label>
                {error ? <SetupError message={error} /> : null}
                <button type="submit" disabled={stage === 'saving-folder'} className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl bg-[#C66B3D] px-6 text-sm font-semibold text-[#E8DCC7] transition hover:bg-[#B08B6E] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#8B9D83]/40 disabled:cursor-not-allowed disabled:opacity-70">
                  {stage === 'saving-folder' ? <><Loader2 size={17} className="animate-spin" /> 正在添加</> : <>添加并继续 <ArrowRight size={17} /></>}
                </button>
                <button type="button" disabled={stage === 'saving-folder'} onClick={() => { setError(''); setStage('complete'); saveProgress({ stage: 'complete', email, folderAdded: false, folderPath }); }} className="min-h-11 w-full text-sm font-semibold text-[#606C38]/70 hover:text-[#606C38]">暂不添加</button>
              </form>
            </>
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
                {error ? <SetupError message={error} /> : null}
                <button type="submit" disabled={stage === 'creating-account'} className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl bg-[#C66B3D] px-6 text-sm font-semibold text-[#E8DCC7] transition hover:bg-[#B08B6E] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#8B9D83]/40 disabled:cursor-not-allowed disabled:opacity-70">
                  {stage === 'creating-account' ? <><Loader2 size={17} className="animate-spin" /> 正在创建账户</> : <>创建账户 <ArrowRight size={17} /></>}
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
              <SetupStep icon={UserRoundPlus} title="创建管理账户" description="设置邮箱和登录密码" complete={accountCreated} active={stage === 'account' || stage === 'creating-account'} />
              <SetupStep icon={FolderPlus} title="添加监控文件夹" description="持续识别目录中的读物" complete={stage === 'complete'} active={folderActive} />
            </ol>
            <p className="mt-auto pt-10 text-xs leading-6 text-[#E8DCC7]/70">账号信息仅保存在你的服务器中。以后可以在设置页面修改邮箱、密码和头像。</p>
          </div>
        </aside>
      </section>
    </main>
  );
}

function SetupError({ message }: { message: string }) {
  return <div role="alert" className="flex items-start gap-2 rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700"><AlertCircle size={17} className="mt-0.5 shrink-0" /><span>{message}</span></div>;
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

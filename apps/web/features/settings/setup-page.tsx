'use client';

import { apiV2Fetch } from '@/lib/api-v2';
import type {
  DirectoryTreeResponse,
  FolderResponse,
  ProblemDetails,
  SessionResponse,
  SetupStatusResponse
} from '@/generated/api-v2';

import { AlertCircle, ArrowRight, Check, Database, FolderPlus, Loader2, ShieldCheck, UserRoundPlus } from 'lucide-react';
import Image from 'next/image';
import { useRouter } from 'next/navigation';
import { FormEvent, useCallback, useEffect, useState } from 'react';
import { CompactLanguageSwitcher } from '../../components/layout/compact-language-switcher';
import { withBasePath } from '../../lib/base-path';
import { PRODUCT_NAME } from '../../lib/brand';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type SetupStage = 'checking' | 'account' | 'creating-account' | 'folder' | 'saving-folder' | 'complete' | 'unavailable';
const setupProgressKey = 'shuku.setup.progress';

type SetupProgress = {
  stage: 'folder' | 'complete' | 'import';
  email: string;
  folderAdded: boolean;
  folderPath: string;
};

export function SetupPage() {
  const { locale, t: i18nAttribute } = useAttributeI18n();
  const router = useRouter();
  const [stage, setStage] = useState<SetupStage>('checking');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [folderName, setFolderName] = useState('我的书库');
  const [folderPath, setFolderPath] = useState('');
  const [folderAdded, setFolderAdded] = useState(false);
  const [error, setError] = useState('');

  function saveProgress(progress: SetupProgress) {
    window.localStorage.setItem(setupProgressKey, JSON.stringify(progress));
  }

  const loadMonitorRoot = useCallback(async (signal?: AbortSignal) => {
    const response = await apiV2Fetch('/api/v2/ingestion/folders/tree', {
      cache: 'no-store',
      credentials: 'same-origin',
      signal
    });
    const payload = await response.json().catch(() => null) as
      | DirectoryTreeResponse
      | ProblemDetails
      | null;
    if (!response.ok || !payload || !('monitorRoot' in payload)) {
      return '';
    }
    return payload.monitorRoot;
  }, []);

  const checkStatus = useCallback(async (signal?: AbortSignal) => {
    setStage('checking');
    setError('');
    try {
      const response = await apiV2Fetch('/api/v2/auth/setup/status', {
        cache: 'no-store',
        credentials: 'same-origin',
        signal
      });
      const payload = await response.json().catch(() => null) as
        | SetupStatusResponse
        | ProblemDetails
        | null;
      if (!response.ok || !payload || !('required' in payload)) {
        throw new Error(payload && 'detail' in payload ? payload.detail : `请求失败（HTTP ${response.status}）`);
      }
      if (payload.required) {
        setStage('account');
        return;
      }

      const session = await apiV2Fetch('/api/v2/account', {
        cache: 'no-store',
        credentials: 'same-origin',
        signal
      });
      if (session.ok) {
        try {
          const saved = JSON.parse(window.localStorage.getItem(setupProgressKey) ?? 'null') as SetupProgress | null;
          if (saved && ['folder', 'import', 'complete'].includes(saved.stage)) {
            const monitorRoot = await loadMonitorRoot(signal);
            setEmail(saved.email);
            setFolderAdded(saved.folderAdded);
            setFolderPath(monitorRoot || saved.folderPath || '');
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
  }, [loadMonitorRoot, router]);

  useEffect(() => {
    const controller = new AbortController();
    void checkStatus(controller.signal);
    return () => controller.abort();
  }, [checkStatus]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim();
    const normalizedEmail = email.trim();
    if (!normalizedName) {
      setError('请输入用户名');
      return;
    }
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
      const response = await apiV2Fetch('/api/v2/auth/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          displayName: normalizedName,
          email: normalizedEmail,
          password,
          locale
        })
      });
      const payload = await response.json().catch(() => null) as SessionResponse | ProblemDetails | null;
      if (response.status === 409) {
        router.replace('/login');
        return;
      }
      if (!response.ok || !payload || !('account' in payload)) {
        throw new Error(payload && 'detail' in payload ? payload.detail : '账户创建失败');
      }
      const accountEmail = payload.account.email ?? normalizedEmail;
      const monitorRoot = await loadMonitorRoot();
      setEmail(accountEmail);
      setFolderPath(monitorRoot);
      setStage('folder');
      saveProgress({
        stage: 'folder',
        email: accountEmail,
        folderAdded: false,
        folderPath: monitorRoot
      });
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
      const response = await apiV2Fetch('/api/v2/ingestion/folders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          path: folderPath.trim(),
          recursive: true,
          options: { name: folderName.trim() || '我的书库' }
        })
      });
      const payload = await response.json().catch(() => null) as FolderResponse | ProblemDetails | null;
      if (!response.ok || !payload || !('path' in payload)) {
        throw new Error(payload && 'detail' in payload ? payload.detail : '监控文件夹添加失败');
      }
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
          <div className="flex items-center justify-between gap-4">
            <div className="flex min-w-0 items-center gap-3">
              <span className="h-12 w-12 shrink-0 overflow-hidden rounded-2xl bg-[#E8DCC7] shadow-sm">
                <Image src={withBasePath('/icons/icon-192.png')} alt="" width={48} height={48} className="h-full w-full object-cover" priority />
              </span>
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-[#C66B3D]">{PRODUCT_NAME}</div>
                <div className="mt-0.5 text-xs text-[#606C38]/70"><I18nText>首次启动设置</I18nText></div>
              </div>
            </div>
            <CompactLanguageSwitcher variant="setup" />
          </div>

          {stage === 'checking' ? (
            <div className="flex min-h-[430px] flex-col items-center justify-center text-center" role="status" aria-live="polite">
              <Loader2 className="animate-spin text-[#C66B3D]" size={30} />
              <h1 className="mt-6 text-2xl font-semibold tracking-[-0.03em]"><I18nText>正在检查系统状态</I18nText></h1>
              <p className="mt-2 text-sm text-[#606C38]/70"><I18nText>确认是否需要创建第一个管理账户</I18nText></p>
            </div>
          ) : stage === 'unavailable' ? (
            <div className="flex min-h-[430px] flex-col items-start justify-center">
              <h1 className="text-3xl font-semibold tracking-[-0.04em]"><I18nText>暂时无法开始设置</I18nText></h1>
              <p className="mt-4 max-w-md text-sm leading-7 text-[#606C38]/80">{error}</p>
              <button type="button" onClick={() => void checkStatus()} className="mt-7 inline-flex min-h-12 items-center justify-center rounded-2xl bg-[#C66B3D] px-6 text-sm font-semibold text-[#E8DCC7] transition hover:bg-[#B08B6E] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#8B9D83]/40">
                <I18nText>重新检查</I18nText></button>
            </div>
          ) : stage === 'complete' ? (
            <div className="flex min-h-[430px] flex-col items-start justify-center" aria-live="polite">
              <span className="flex h-14 w-14 items-center justify-center rounded-[20px] bg-[#8B9D83] text-[#E8DCC7]"><Check size={28} strokeWidth={2.4} /></span>
              <h1 className="mt-7 text-3xl font-semibold tracking-[-0.04em] sm:text-4xl"><I18nText>你的私人书库已准备好</I18nText></h1>
              <p className="mt-4 text-sm leading-7 text-[#606C38]/80">{i18nAttribute('管理账户 {value0} 已创建并登录。', { value0: email })}{folderAdded ? i18nAttribute("监控文件夹已启用，系统会自动识别目录中已有和以后新增的读物。") : i18nAttribute("你可以稍后在设置中添加监控文件夹。")}</p>
              <button type="button" onClick={() => { window.localStorage.removeItem(setupProgressKey); router.replace('/library'); router.refresh(); }} className="mt-8 inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl bg-[#C66B3D] px-6 text-sm font-semibold text-[#E8DCC7] transition hover:bg-[#B08B6E] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#8B9D83]/40">
                <I18nText>进入书库 </I18nText><ArrowRight size={17} />
              </button>
            </div>
          ) : stage === 'folder' || stage === 'saving-folder' ? (
            <>
              <div className="mt-10 max-w-xl">
                <div className="text-sm font-semibold text-[#C66B3D]"><I18nText>第 2 步，共 2 步</I18nText></div>
                <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] sm:text-4xl"><I18nText>添加监控文件夹</I18nText></h1>
                <p className="mt-3 text-sm leading-7 text-[#606C38]/80"><I18nText>把服务器或 NAS 上的读物目录加入监控。目录内已有和以后新增的支持格式都会由后台自动识别。</I18nText></p>
              </div>
              <form onSubmit={saveFolder} className="mt-8 space-y-4">
                <label className="block">
                  <span className="text-sm font-semibold"><I18nText>文件夹名称</I18nText></span>
                  <input value={folderName} onChange={(event) => { setFolderName(event.target.value); setError(''); }} maxLength={100} className="mt-2 h-12 w-full rounded-2xl border border-[#B08B6E]/55 bg-[#E8DCC7] px-4 text-sm outline-none transition focus:border-[#C66B3D] focus:ring-4 focus:ring-[#C66B3D]/15" />
                </label>
                <label className="block">
                  <span className="text-sm font-semibold"><I18nText>监控文件夹路径</I18nText></span>
                  <input value={folderPath} onChange={(event) => { setFolderPath(event.target.value); setError(''); }} placeholder="/monitor" className="mt-2 h-12 w-full rounded-2xl border border-[#B08B6E]/55 bg-[#E8DCC7] px-4 text-sm outline-none transition placeholder:text-[#8B9D83] focus:border-[#C66B3D] focus:ring-4 focus:ring-[#C66B3D]/15" />
                  <span className="mt-2 block text-xs leading-5 text-[#606C38]/65"><I18nText>路径必须位于应用可访问的监控根目录内；Docker 部署通常为 /monitor。</I18nText></span>
                </label>
                {error ? <SetupError message={error} /> : null}
                <button type="submit" disabled={stage === 'saving-folder'} className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl bg-[#C66B3D] px-6 text-sm font-semibold text-[#E8DCC7] transition hover:bg-[#B08B6E] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#8B9D83]/40 disabled:cursor-not-allowed disabled:opacity-70">
                  {stage === 'saving-folder' ? <><Loader2 size={17} className="animate-spin" /> <I18nText>正在添加</I18nText></> : <><I18nText>添加并继续 </I18nText><ArrowRight size={17} /></>}
                </button>
                <button type="button" disabled={stage === 'saving-folder'} onClick={() => { setError(''); setStage('complete'); saveProgress({ stage: 'complete', email, folderAdded: false, folderPath }); }} className="min-h-11 w-full text-sm font-semibold text-[#606C38]/70 hover:text-[#606C38]"><I18nText>暂不添加</I18nText></button>
              </form>
            </>
          ) : (
            <>
              <div className="mt-10 max-w-xl">
                <h1 className="text-3xl font-semibold tracking-[-0.045em] sm:text-4xl"><I18nText>创建你的管理账户</I18nText></h1>
                <p className="mt-3 text-sm leading-7 text-[#606C38]/80"><I18nText>该账户用于登录和管理这套私人图书馆。创建后，系统不会再开放初始化入口。</I18nText></p>
              </div>

              <form data-testid="setup-form" onSubmit={submit} noValidate className="mt-8 space-y-4">
                <label className="block">
                  <span className="text-sm font-semibold"><I18nText>用户名</I18nText></span>
                  <input autoFocus type="text" required minLength={1} maxLength={40} value={name} onChange={(event) => { setName(event.target.value); setError(''); }} autoComplete="name" placeholder={i18nAttribute("例如：二毛")} className="mt-2 h-12 w-full rounded-2xl border border-[#B08B6E]/55 bg-[#E8DCC7] px-4 text-sm text-[#606C38] outline-none transition placeholder:text-[#8B9D83] focus:border-[#C66B3D] focus:ring-4 focus:ring-[#C66B3D]/15" />
                </label>
                <label className="block">
                  <span className="text-sm font-semibold"><I18nText>登录邮箱</I18nText></span>
                  <input type="email" required maxLength={191} value={email} onChange={(event) => { setEmail(event.target.value); setError(''); }} autoComplete="username" placeholder="name@example.com" className="mt-2 h-12 w-full rounded-2xl border border-[#B08B6E]/55 bg-[#E8DCC7] px-4 text-sm text-[#606C38] outline-none transition placeholder:text-[#8B9D83] focus:border-[#C66B3D] focus:ring-4 focus:ring-[#C66B3D]/15" />
                </label>
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="block">
                    <span className="text-sm font-semibold"><I18nText>登录密码</I18nText></span>
                    <input type="password" required minLength={10} maxLength={128} value={password} onChange={(event) => { setPassword(event.target.value); setError(''); }} autoComplete="new-password" placeholder={i18nAttribute("至少 10 位")} className="mt-2 h-12 w-full rounded-2xl border border-[#B08B6E]/55 bg-[#E8DCC7] px-4 text-sm text-[#606C38] outline-none transition placeholder:text-[#8B9D83] focus:border-[#C66B3D] focus:ring-4 focus:ring-[#C66B3D]/15" />
                  </label>
                  <label className="block">
                    <span className="text-sm font-semibold"><I18nText>确认密码</I18nText></span>
                    <input type="password" required minLength={10} maxLength={128} value={confirmPassword} onChange={(event) => { setConfirmPassword(event.target.value); setError(''); }} autoComplete="new-password" placeholder={i18nAttribute("再次输入密码")} className="mt-2 h-12 w-full rounded-2xl border border-[#B08B6E]/55 bg-[#E8DCC7] px-4 text-sm text-[#606C38] outline-none transition placeholder:text-[#8B9D83] focus:border-[#C66B3D] focus:ring-4 focus:ring-[#C66B3D]/15" />
                  </label>
                </div>
                {error ? <SetupError message={error} /> : null}
                <button type="submit" disabled={stage === 'creating-account'} className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl bg-[#C66B3D] px-6 text-sm font-semibold text-[#E8DCC7] transition hover:bg-[#B08B6E] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#8B9D83]/40 disabled:cursor-not-allowed disabled:opacity-70">
                  {stage === 'creating-account' ? <><Loader2 size={17} className="animate-spin" /> <I18nText>正在创建账户</I18nText></> : <><I18nText>创建账户 </I18nText><ArrowRight size={17} /></>}
                </button>
              </form>
            </>
          )}
        </div>

        <aside className="bg-[#606C38] p-7 text-[#E8DCC7] sm:p-10 lg:p-12">
          <div className="flex h-full flex-col">
            <ShieldCheck size={28} strokeWidth={1.8} />
            <h2 className="mt-6 text-xl font-semibold tracking-[-0.03em]"><I18nText>初始化清单</I18nText></h2>
            <ol className="mt-8 space-y-6">
              <SetupStep icon={Database} title={i18nAttribute("检查系统状态")} description={i18nAttribute("确认数据库和存储目录可用")} complete={statusChecked} active={stage === 'checking' || stage === 'unavailable'} />
              <SetupStep icon={UserRoundPlus} title={i18nAttribute("创建管理账户")} description={i18nAttribute("设置用户名、邮箱和登录密码")} complete={accountCreated} active={stage === 'account' || stage === 'creating-account'} />
              <SetupStep icon={FolderPlus} title={i18nAttribute("添加监控文件夹")} description={i18nAttribute("持续识别目录中的读物")} complete={stage === 'complete'} active={folderActive} />
            </ol>
            <p className="mt-auto pt-10 text-xs leading-6 text-[#E8DCC7]/70"><I18nText>账号信息仅保存在你的服务器中。以后可以在设置页面修改用户名、邮箱、密码和头像。</I18nText></p>
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

'use client';

import { AlertCircle, ArrowRight, Check, Database, FolderOpen, FolderPlus, LibraryBig, Loader2, Plus, ShieldCheck, Trash2, UserRoundPlus, X } from 'lucide-react';
import Image from 'next/image';
import { useRouter } from 'next/navigation';
import { FormEvent, ReactNode, useCallback, useEffect, useState } from 'react';
import { CompactLanguageSwitcher } from '../../components/layout/compact-language-switcher';
import { withBasePath } from '../../lib/base-path';
import { PRODUCT_NAME } from '../../lib/brand';
import { I18nText, useI18n } from '@/i18n/provider';
import { loadLibraryDirectory } from './api/libraries-client';
import { organizationModeLabel, type OrganizationMode } from './model/organization-mode';
import { DirectoryPathPicker } from './ui/directory-path-picker';
import { OrganizationModePicker } from './ui/organization-mode-picker';

type SetupStage = 'checking' | 'account' | 'creating-account' | 'library' | 'checking-library' | 'saving-library' | 'activating' | 'unavailable';
type SetupPayload = { ok: boolean; data?: { initialized?: boolean; user?: { email?: string } }; error?: { message?: string }; detail?: Array<{ loc?: Array<string | number> }> };
type SetupLibrary = { id: string; name: string; rootPath: string; organizationMode: OrganizationMode };
type LibraryPayload = { ok: boolean; data?: { library?: SetupLibrary }; error?: { message?: string } };
type SetupProgress = { stage: 'library'; email: string; libraries: SetupLibrary[] };
type StoredSetupProgress = SetupProgress | { stage: 'summary' | 'complete'; email: string; libraries: SetupLibrary[] };
const setupProgressKey = 'shuku.setup.progress';

async function readSetupPayload(response: Response): Promise<SetupPayload> {
  if ((response.headers.get('content-type') ?? '').includes('application/json')) {
    const payload = await response.json() as SetupPayload;
    if (!payload.error?.message && payload.detail?.length) {
      const passwordError = payload.detail.some((item) => item.loc?.includes('password'));
      return { ...payload, error: { message: passwordError ? '密码格式不正确，请至少输入 10 位' : '账户信息格式不正确，请检查后重试' } };
    }
    return payload;
  }
  const message = await response.text().catch(() => '');
  return { ok: false, error: { message: message.trim() || `请求失败（HTTP ${response.status}）` } };
}

export function SetupPage() {
  const { locale, t } = useI18n();
  const router = useRouter();
  const [stage, setStage] = useState<SetupStage>('checking');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [libraryName, setLibraryName] = useState('我的书库');
  const [libraryPath, setLibraryPath] = useState('');
  const [organizationMode, setOrganizationMode] = useState<OrganizationMode | null>(null);
  const [libraries, setLibraries] = useState<SetupLibrary[]>([]);
  const [libraryDialogOpen, setLibraryDialogOpen] = useState(false);
  const [error, setError] = useState('');
  const saveProgress = useCallback((progress: SetupProgress) => window.localStorage.setItem(setupProgressKey, JSON.stringify(progress)), []);

  const checkStatus = useCallback(async (signal?: AbortSignal) => {
    setStage('checking');
    setError('');
    try {
      const response = await fetch('/api/auth/setup/status', { cache: 'no-store', credentials: 'same-origin', signal });
      const payload = await readSetupPayload(response);
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '无法检查系统状态');
      if (!payload.data?.initialized) return setStage('account');
      const session = await fetch('/api/auth/me', { cache: 'no-store', credentials: 'same-origin', signal });
      if (session.ok) {
        try {
          const saved = JSON.parse(window.localStorage.getItem(setupProgressKey) ?? 'null') as StoredSetupProgress | null;
          if (saved?.stage === 'complete') {
            window.localStorage.removeItem(setupProgressKey); router.replace('/library'); return;
          }
          if (saved && ['library', 'summary'].includes(saved.stage)) {
            setEmail(saved.email); setLibraries(saved.libraries ?? []); setStage('library'); return;
          }
        } catch { window.localStorage.removeItem(setupProgressKey); }
      }
      router.replace(session.ok ? '/library' : '/login');
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') return;
      setError(reason instanceof Error ? reason.message : '无法连接初始化服务'); setStage('unavailable');
    }
  }, [router]);

  useEffect(() => { const controller = new AbortController(); void checkStatus(controller.signal); return () => controller.abort(); }, [checkStatus]);

  async function createAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim(); const normalizedEmail = email.trim();
    if (!normalizedName) return setError('请输入用户名');
    if (!normalizedEmail) return setError('请输入登录邮箱');
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) return setError('请输入有效的邮箱地址');
    if (!password) return setError('请输入登录密码');
    if (password.length < 10) return setError('密码至少需要 10 位');
    if (!confirmPassword) return setError('请再次输入登录密码');
    if (password !== confirmPassword) return setError('两次输入的密码不一致');
    setStage('creating-account'); setError('');
    try {
      const response = await fetch('/api/auth/setup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify({ name: normalizedName, email: normalizedEmail, password, locale }) });
      const payload = await readSetupPayload(response);
      if (response.status === 409) return router.replace('/login');
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '账户创建失败');
      const accountEmail = payload.data?.user?.email ?? normalizedEmail;
      setEmail(accountEmail); setStage('library'); saveProgress({ stage: 'library', email: accountEmail, libraries: [] });
    } catch (reason) { setError(reason instanceof Error ? reason.message : '无法连接初始化服务'); setStage('account'); }
  }

  async function addLibrary(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const rootPath = libraryPath.trim();
    if (!rootPath) return setError('请输入书库路径');
    const selectedMode = organizationMode;
    if (!selectedMode) return setError('请选择文件组织方式');
    setStage('checking-library'); setError('');
    try {
      await loadLibraryDirectory(rootPath);
      setStage('saving-library');
      const response = await fetch('/api/libraries', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify({ name: libraryName.trim() || '我的书库', rootPath, organizationMode: selectedMode, enabled: false, ignorePatterns: '', ignoreHidden: true, minFileSizeBytes: 0 }) });
      const payload = await response.json() as LibraryPayload;
      if (!response.ok || !payload.ok || !payload.data?.library) throw new Error(payload.error?.message ?? '书库添加失败');
      const nextLibraries = [...libraries, payload.data.library];
      setLibraries(nextLibraries); setLibraryName('我的书库'); setLibraryPath(''); setOrganizationMode(null); setLibraryDialogOpen(false); setStage('library');
      saveProgress({ stage: 'library', email, libraries: nextLibraries });
    } catch (reason) { setError(reason instanceof Error ? reason.message : '书库快速检查失败'); setStage('library'); }
  }

  async function removeLibrary(library: SetupLibrary) {
    setError('');
    const response = await fetch(`/api/libraries/${library.id}`, { method: 'DELETE', credentials: 'same-origin' });
    const payload = await response.json() as { ok: boolean; error?: { message?: string } };
    if (!response.ok || !payload.ok) return setError(payload.error?.message ?? '移除书库失败');
    const next = libraries.filter((candidate) => candidate.id !== library.id); setLibraries(next); saveProgress({ stage: 'library', email, libraries: next });
  }

  async function activateLibraries() {
    setStage('activating'); setError('');
    try {
      await Promise.all(libraries.map(async (library) => {
        const response = await fetch(`/api/libraries/${library.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify({ enabled: true }) });
        const payload = await response.json() as LibraryPayload;
        if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '启用书库失败');
      }));
      window.localStorage.removeItem(setupProgressKey); router.replace('/library'); router.refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '启用书库失败'); setStage('library'); }
  }

  function skipLibrarySetup() { window.localStorage.removeItem(setupProgressKey); router.replace('/library'); router.refresh(); }
  const statusChecked = stage !== 'checking' && stage !== 'unavailable';
  const accountCreated = !['checking', 'account', 'creating-account', 'unavailable'].includes(stage);
  const configuring = ['library', 'checking-library', 'saving-library', 'activating'].includes(stage);

  return <main data-testid="setup-page" className="shuku-auth-safe-screen flex min-h-[100dvh] items-center justify-center bg-[#E8DCC7] p-4 text-[#606C38] sm:p-8" style={{ fontFamily: '"Avenir Next", "PingFang SC", sans-serif' }}>
    <section className="grid w-full max-w-[1280px] overflow-hidden rounded-[32px] border border-[#B08B6E]/40 bg-[#D4B895] shadow-[0_30px_90px_rgba(96,108,56,0.16)] lg:grid-cols-[minmax(0,1.55fr)_360px]">
      <div className="p-6 sm:p-10 lg:p-12"><SetupHeader />
        {stage === 'checking' ? <CenteredStatus icon={<Loader2 className="animate-spin" size={30} />} title={t('正在检查系统状态')} description={t('确认是否需要创建第一个管理账户')} /> : null}
        {stage === 'unavailable' ? <Unavailable error={error} onRetry={() => void checkStatus()} /> : null}
        {stage === 'account' || stage === 'creating-account' ? <AccountForm stage={stage} name={name} email={email} password={password} confirmPassword={confirmPassword} error={error} setName={setName} setEmail={setEmail} setPassword={setPassword} setConfirmPassword={setConfirmPassword} clearError={() => setError('')} onSubmit={createAccount} /> : null}
        {['library', 'checking-library', 'saving-library', 'activating'].includes(stage) ? <LibraryWorkspace stage={stage} name={libraryName} path={libraryPath} mode={organizationMode} libraries={libraries} error={error} dialogOpen={libraryDialogOpen} setName={setLibraryName} setPath={setLibraryPath} setMode={setOrganizationMode} clearError={() => setError('')} onOpenDialog={() => { setError(''); setLibraryDialogOpen(true); }} onCloseDialog={() => { if (stage === 'library') { setError(''); setLibraryDialogOpen(false); } }} onSubmit={addLibrary} onRemove={removeLibrary} onActivate={() => void activateLibraries()} onSkip={skipLibrarySetup} /> : null}
      </div>
      <SetupAside statusChecked={statusChecked} accountCreated={accountCreated} configuring={configuring} count={libraries.length} />
    </section>
  </main>;
}

function SetupHeader() { return <div className="flex items-center justify-between gap-4"><div className="flex items-center gap-3"><span className="h-12 w-12 overflow-hidden rounded-2xl bg-[#E8DCC7] shadow-sm"><Image src={withBasePath('/icons/icon-192.png')} alt="" width={48} height={48} priority /></span><div><div className="text-sm font-semibold text-[#C66B3D]">{PRODUCT_NAME}</div><div className="text-xs text-[#606C38]/70"><I18nText>首次启动设置</I18nText></div></div></div><CompactLanguageSwitcher variant="setup" /></div>; }
function CenteredStatus({ icon, title, description }: { icon: ReactNode; title: string; description: string }) { return <div className="flex min-h-[500px] flex-col items-center justify-center text-center" role="status">{icon}<h1 className="mt-6 text-2xl font-semibold">{title}</h1><p className="mt-2 text-sm text-[#606C38]/70">{description}</p></div>; }
function Unavailable({ error, onRetry }: { error: string; onRetry: () => void }) { return <div className="flex min-h-[500px] flex-col items-start justify-center"><h1 className="text-3xl font-semibold"><I18nText>暂时无法开始设置</I18nText></h1><p className="mt-4 text-sm leading-7">{error}</p><button type="button" onClick={onRetry} className="mt-7 min-h-12 rounded-2xl bg-[#C66B3D] px-6 text-sm font-semibold text-[#E8DCC7]"><I18nText>重新检查</I18nText></button></div>; }

type AccountProps = { stage: SetupStage; name: string; email: string; password: string; confirmPassword: string; error: string; setName: (v: string) => void; setEmail: (v: string) => void; setPassword: (v: string) => void; setConfirmPassword: (v: string) => void; clearError: () => void; onSubmit: (e: FormEvent<HTMLFormElement>) => void };
function AccountForm(p: AccountProps) {
  const { t } = useI18n(); const busy = p.stage === 'creating-account'; const input = 'mt-2 h-12 w-full rounded-2xl border border-[#B08B6E]/55 bg-[#E8DCC7] px-4 text-sm outline-none focus:border-[#C66B3D] focus:ring-4 focus:ring-[#C66B3D]/15';
  return <><div className="mt-10"><h1 className="text-3xl font-semibold sm:text-4xl"><I18nText>创建你的管理账户</I18nText></h1><p className="mt-3 text-sm leading-7 text-[#606C38]/80"><I18nText>该账户用于登录和管理这套私人图书馆。创建后，系统不会再开放初始化入口。</I18nText></p></div><form data-testid="setup-form" onSubmit={p.onSubmit} className="mt-8 max-w-2xl space-y-4"><label className="block"><span className="text-sm font-semibold"><I18nText>用户名</I18nText></span><input autoFocus value={p.name} onChange={(e) => { p.setName(e.target.value); p.clearError(); }} placeholder={t('例如：二毛')} className={input} /></label><label className="block"><span className="text-sm font-semibold"><I18nText>登录邮箱</I18nText></span><input type="email" value={p.email} onChange={(e) => { p.setEmail(e.target.value); p.clearError(); }} placeholder="name@example.com" className={input} /></label><div className="grid gap-4 sm:grid-cols-2"><label><span className="text-sm font-semibold"><I18nText>登录密码</I18nText></span><input type="password" value={p.password} onChange={(e) => { p.setPassword(e.target.value); p.clearError(); }} placeholder={t('至少 10 位')} className={input} /></label><label><span className="text-sm font-semibold"><I18nText>确认密码</I18nText></span><input type="password" value={p.confirmPassword} onChange={(e) => { p.setConfirmPassword(e.target.value); p.clearError(); }} placeholder={t('再次输入密码')} className={input} /></label></div>{p.error ? <SetupError message={p.error} /> : null}<PrimaryButton busy={busy} busyLabel={t('正在创建账户')} label={t('创建账户')} /></form></>;
}
type LibraryWorkspaceProps = { stage: SetupStage; name: string; path: string; mode: OrganizationMode | null; libraries: SetupLibrary[]; error: string; dialogOpen: boolean; setName: (v: string) => void; setPath: (v: string) => void; setMode: (v: OrganizationMode) => void; clearError: () => void; onOpenDialog: () => void; onCloseDialog: () => void; onSubmit: (e: FormEvent<HTMLFormElement>) => void; onRemove: (library: SetupLibrary) => void; onActivate: () => void; onSkip: () => void };

function LibraryWorkspace(p: LibraryWorkspaceProps) {
  const { t } = useI18n();
  const [skipConfirmationOpen, setSkipConfirmationOpen] = useState(false);
  const busy = p.stage === 'checking-library' || p.stage === 'saving-library' || p.stage === 'activating';
  return <>
    <div className="mt-9">
      <div className="text-sm font-semibold text-[#C66B3D]"><I18nText>第 2 步，共 2 步</I18nText></div>
      <h1 className="mt-2 text-3xl font-semibold sm:text-4xl"><I18nText>添加书库</I18nText></h1>
      <p className="mt-3 text-sm leading-7 text-[#606C38]/80"><I18nText>每个书库可以独立选择路径和文件组织方式，添加后仍可继续新增。</I18nText></p>
    </div>
    <section aria-label={t('书库清单')} className={`mt-8 grid gap-4 ${p.libraries.length === 0 ? 'min-h-[330px] place-items-center' : 'sm:grid-cols-2 xl:grid-cols-3'}`}>
      {p.libraries.map((library) => <article key={library.id} className="group relative flex min-h-44 flex-col rounded-3xl border border-[#B08B6E]/45 bg-[#E8DCC7]/70 p-5 shadow-sm">
        <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#8B9D83]/20"><FolderOpen size={20} /></span>
        <h2 className="mt-4 truncate text-base font-semibold">{library.name}</h2>
        <p className="mt-1 truncate text-xs text-[#606C38]/60">{library.rootPath}</p>
        <div className="mt-auto flex items-center justify-between pt-4"><span className="rounded-full bg-[#606C38]/10 px-3 py-1 text-xs font-semibold">{t(organizationModeLabel(library.organizationMode))}</span><button type="button" disabled={busy} onClick={() => void p.onRemove(library)} aria-label={t('移除书库')} className="flex h-10 w-10 items-center justify-center rounded-xl text-[#9E4D29] transition hover:bg-[#C66B3D]/10 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#C66B3D]/25 disabled:opacity-50"><Trash2 size={17} /></button></div>
      </article>)}
      <button type="button" onClick={p.onOpenDialog} disabled={busy} className={`flex aspect-square flex-col items-center justify-center rounded-3xl border-2 border-dashed border-[#606C38]/35 bg-[#E8DCC7]/35 p-6 text-center transition hover:border-[#C66B3D] hover:bg-[#E8DCC7]/65 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#C66B3D]/25 disabled:opacity-60 ${p.libraries.length === 0 ? 'w-48' : 'w-full'}`}>
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[#C66B3D] text-[#F2E8D5]"><Plus size={26} /></span>
        <span className="mt-4 text-base font-semibold"><I18nText>添加书库</I18nText></span>
        <span className="mt-1 text-xs text-[#606C38]/65"><I18nText>选择路径和组织方式</I18nText></span>
      </button>
    </section>
    {p.error && !p.dialogOpen ? <div className="mt-5"><SetupError message={p.error} /></div> : null}
    <div className="mt-7 flex justify-center">
      {p.libraries.length > 0 ? <button type="button" disabled={busy} onClick={p.onActivate} className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl bg-[#C66B3D] px-6 text-sm font-semibold text-[#E8DCC7] disabled:opacity-70">{p.stage === 'activating' ? <Loader2 size={17} className="animate-spin" /> : <ArrowRight size={17} />}{p.stage === 'activating' ? t('正在启用书库') : t('确认')}</button> : <button type="button" onClick={() => setSkipConfirmationOpen(true)} className="px-3 py-2 text-sm font-semibold text-[#606C38]/70 underline decoration-1 underline-offset-4 transition hover:text-[#C43D2F] focus-visible:rounded-lg focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#C66B3D]/25"><I18nText>跳过</I18nText></button>}
    </div>
    {p.dialogOpen ? <LibraryDialog {...p} busy={busy} /> : null}
    {skipConfirmationOpen ? <SkipLibraryConfirmation onCancel={() => setSkipConfirmationOpen(false)} onConfirm={() => { setSkipConfirmationOpen(false); p.onSkip(); }} /> : null}
  </>;
}

function LibraryDialog(p: LibraryWorkspaceProps & { busy: boolean }) {
  const { t } = useI18n();
  const { busy, onCloseDialog } = p;
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) onCloseDialog(); };
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', handleKeyDown);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener('keydown', handleKeyDown); };
  }, [busy, onCloseDialog]);
  return <div className="fixed inset-0 z-[100] flex items-center justify-center bg-[#3B4423]/55 p-4 backdrop-blur-sm" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) p.onCloseDialog(); }}>
    <section role="dialog" aria-modal="true" aria-labelledby="add-library-dialog-title" className="relative max-h-[calc(100dvh-2rem)] w-full max-w-5xl overflow-visible rounded-[30px] border border-[#B08B6E]/45 bg-[#D4B895] p-5 shadow-[0_30px_90px_rgba(35,42,19,0.35)] sm:p-8">
      <button type="button" onClick={p.onCloseDialog} disabled={p.busy} aria-label={t('关闭')} className="absolute right-5 top-5 flex h-11 w-11 items-center justify-center rounded-2xl bg-[#E8DCC7]/75 transition hover:bg-[#E8DCC7] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#C66B3D]/25 disabled:opacity-50"><X size={20} /></button>
      <div className="pr-14"><h2 id="add-library-dialog-title" className="text-2xl font-semibold sm:text-3xl"><I18nText>新增书库</I18nText></h2><p className="mt-2 text-sm leading-6 text-[#606C38]/75"><I18nText>路径和组织方式一起保存，添加后仍可继续新增或删除。</I18nText></p></div>
      <form onSubmit={p.onSubmit} className="mt-6 space-y-5">
        <div className="grid gap-4 md:grid-cols-[0.7fr_1.3fr]"><label><span className="text-sm font-semibold"><I18nText>书库名称</I18nText></span><input autoFocus value={p.name} onChange={(e) => { p.setName(e.target.value); p.clearError(); }} disabled={p.busy} className="mt-2 h-12 w-full rounded-2xl border border-[#B08B6E]/55 bg-[#E8DCC7] px-4 text-sm outline-none focus:border-[#C66B3D] focus:ring-4 focus:ring-[#C66B3D]/15 disabled:opacity-60" /></label><div><span className="text-sm font-semibold"><I18nText>书库路径</I18nText></span><DirectoryPathPicker value={p.path} onChange={(v) => { p.setPath(v); p.clearError(); }} disabled={p.busy} variant="setup" /></div></div>
        <div><span className="text-sm font-semibold"><I18nText>文件组织方式</I18nText></span><div className="mt-2"><OrganizationModePicker value={p.mode} onChange={(v) => { p.setMode(v); p.clearError(); }} disabled={p.busy} /></div></div>
        {p.error ? <SetupError message={p.error} /> : null}
        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end"><button type="button" disabled={p.busy} onClick={p.onCloseDialog} className="min-h-12 rounded-2xl px-6 text-sm font-semibold text-[#606C38]/70 disabled:opacity-50"><I18nText>取消</I18nText></button><button type="submit" disabled={p.busy} className="inline-flex min-h-12 min-w-36 items-center justify-center gap-2 rounded-2xl bg-[#C66B3D] px-7 text-sm font-semibold text-[#E8DCC7] disabled:opacity-70">{p.busy ? <Loader2 size={17} className="animate-spin" /> : null}{p.busy ? (p.stage === 'checking-library' ? t('正在快速检查') : t('正在添加书库')) : t('添加')}</button></div>
      </form>
    </section>
  </div>;
}

function SkipLibraryConfirmation({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onCancel(); };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onCancel]);
  return <div className="fixed inset-0 z-[120] flex items-center justify-center bg-[#3B4423]/55 p-4 backdrop-blur-sm" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onCancel(); }}>
    <section role="alertdialog" aria-modal="true" aria-labelledby="skip-library-title" aria-describedby="skip-library-description" className="w-full max-w-md rounded-[28px] border border-[#B08B6E]/45 bg-[#D4B895] p-6 shadow-[0_30px_90px_rgba(35,42,19,0.35)] sm:p-7">
      <h2 id="skip-library-title" className="text-xl font-semibold"><I18nText>确认跳过添加书库？</I18nText></h2>
      <p id="skip-library-description" className="mt-3 text-sm leading-6 text-[#606C38]/75"><I18nText>跳过后将直接完成初始化，你仍可以稍后在设置中添加书库。</I18nText></p>
      <div className="mt-6 flex justify-end gap-3"><button type="button" onClick={onCancel} className="min-h-11 rounded-xl px-5 text-sm font-semibold text-[#606C38]/75"><I18nText>返回添加</I18nText></button><button type="button" onClick={onConfirm} className="min-h-11 rounded-xl bg-[#C66B3D] px-5 text-sm font-semibold text-[#F2E8D5]"><I18nText>确认跳过</I18nText></button></div>
    </section>
  </div>;
}

function PrimaryButton({ busy, busyLabel, label }: { busy: boolean; busyLabel: string; label: string }) { return <button type="submit" disabled={busy} className="inline-flex min-h-12 flex-1 items-center justify-center gap-2 rounded-2xl bg-[#C66B3D] px-6 text-sm font-semibold text-[#E8DCC7] disabled:opacity-70">{busy ? <Loader2 size={17} className="animate-spin" /> : null}{busy ? busyLabel : label}{busy ? null : <ArrowRight size={17} />}</button>; }
function SetupError({ message }: { message: string }) { return <div role="alert" className="flex items-start gap-2 rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700"><AlertCircle size={17} className="mt-0.5" /><span>{message}</span></div>; }

function SetupAside({ statusChecked, accountCreated, configuring, count }: { statusChecked: boolean; accountCreated: boolean; configuring: boolean; count: number }) {
  const { t } = useI18n(); return <aside className="bg-[#606C38] p-7 text-[#E8DCC7] sm:p-10"><div className="flex h-full flex-col"><ShieldCheck size={28} /><h2 className="mt-6 text-xl font-semibold"><I18nText>初始化清单</I18nText></h2><ol className="mt-8 space-y-6"><SetupStep icon={Database} title={t('检查系统状态')} description={t('确认数据库和存储目录可用')} complete={statusChecked} active={!statusChecked} /><SetupStep icon={UserRoundPlus} title={t('创建管理账户')} description={t('设置用户名、邮箱和登录密码')} complete={accountCreated} active={statusChecked && !accountCreated} /><SetupStep icon={LibraryBig} title={t('添加书库')} description={count ? t('已添加 {value0} 个书库', { value0: count }) : t('路径与组织方式一起设置')} complete={false} active={configuring} /></ol><p className="mt-auto pt-8 text-xs leading-6 text-[#E8DCC7]/70"><I18nText>账号信息仅保存在你的服务器中。以后可以在设置页面继续管理书库。</I18nText></p></div></aside>;
}
function SetupStep({ icon: Icon, title, description, complete, active }: { icon: typeof FolderPlus; title: string; description: string; complete: boolean; active: boolean }) { return <li className="flex gap-4"><span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl ${complete ? 'bg-[#8B9D83]' : active ? 'bg-[#C66B3D]' : 'bg-[#8B9D83]/25'}`}>{complete ? <Check size={18} /> : <Icon size={18} />}</span><span><span className="block text-sm font-semibold">{title}</span><span className="mt-1 block text-xs leading-5 text-[#E8DCC7]/65">{description}</span></span></li>; }

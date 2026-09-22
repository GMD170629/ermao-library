'use client';

import { Copy, Download, KeyRound, ShieldCheck } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAppSession } from '../../../components/layout/app-session-context';
import { Button } from '../../../components/ui/button';
import { Select } from '../../../components/ui/select';
import { useToast } from '../../../components/ui/feedback';
import { useI18n } from '../../../i18n/provider';
import type { UpdateGrantRequest, CreateGrantRequest, GrantView, Scope } from '../../../generated/automation';
import { SettingsCenterShell, SettingsTabs } from '../../settings/public';
import { revealGrant } from '../api/client';
import { useAutomation } from '../application/use-automation';
import { canCancelOperation, operationStatusLabel, clientTemplate, connectionUrl, scopeLabels, scopes, selectedScopes, type LibraryChoice, type ServiceSettings, type McpClient } from '../model/configuration';

const panel = 'rounded-[20px] border border-[var(--visual-color-app-divider-strong)] bg-[var(--visual-color-app-surface-raised)] p-5';
const choiceControl = 'h-4 w-4 shrink-0 accent-[var(--visual-color-app-brand-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--visual-color-app-focus-ring)]';
const input = 'w-full rounded-xl border border-[var(--visual-color-app-divider-strong)] bg-white px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--visual-color-app-focus-ring)]';

function ScopeChoices({ selected, available, change }: { selected: Scope[]; available: Scope[]; change: (next: Scope[]) => void }) {
  const { t } = useI18n();
  const groups: { label: string; scopes: Scope[] }[] = [
    { label: '系统能力', scopes: ['system:read', 'system:manage'] },
    { label: '图书数据', scopes: ['books:write', 'shelves:write'] },
    { label: '源文件操作', scopes: ['files:upload', 'files:modify'] }
  ];
  return <div className="space-y-4">{groups.map((group) => {
    const visible = group.scopes.filter((scope) => available.includes(scope));
    return visible.length ? <fieldset key={group.label}><legend className="mb-2 text-xs text-[#77716A]">{t(group.label)}</legend><div className="grid gap-3 sm:grid-cols-2">{visible.map((scope) => <label key={scope} className="flex min-h-9 items-center gap-3 text-sm">
      <input type="checkbox" checked={selected.includes(scope)} disabled={scope === 'system:read'} onChange={(event) => change(selectedScopes(selected, scope, event.target.checked))} className={choiceControl} />
      {t(scopeLabels[scope])}
    </label>)}</div></fieldset> : null;
  })}</div>;
}

function ServiceForm({ settings, busy, save }: { settings: ServiceSettings; busy: boolean; save: (value: ServiceSettings) => Promise<boolean | undefined> }) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(settings);
  return <form className={panel} onSubmit={(event) => { event.preventDefault(); void save(draft); }}>
    <h3 className="mb-3 flex items-center gap-2 font-semibold"><ShieldCheck size={20} />{t('MCP 服务')}</h3>
    <label className="flex items-center gap-3 text-sm"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} />{t('启用 MCP 服务')}</label>
    <p className="mt-2 text-sm text-[#77716A]">{t('关闭后，客户端不能继续调用；已经发布的文件只完成必要的一致性修复。')}</p>
    <label className="mt-4 block text-sm">{t('公开 URL')}<input type="url" required={draft.enabled} className={`${input} mt-2`} value={draft.publicBaseUrl} onChange={(event) => setDraft({ ...draft, publicBaseUrl: event.target.value })} placeholder="https://books.example.com/books" data-i18n-skip /></label>
    <p className="mt-2 text-xs text-[#77716A]">{t('填写网站根地址，包含部署前缀；系统会自动添加 /api/mcp。')}</p>
    <fieldset className="mt-5"><legend className="mb-3 text-sm font-medium">{t('允许用户授权的能力')}</legend><ScopeChoices selected={draft.enabledScopes} available={scopes} change={(enabledScopes) => setDraft({ ...draft, enabledScopes })} /></fieldset>
    <Button className="mt-5" type="submit" loading={busy}>{t('保存服务设置')}</Button>
  </form>;
}

function GrantForm({ libraries, available, busy, create, cancel, initial }: { initial?: GrantView; libraries: LibraryChoice[]; available: Scope[]; busy: boolean; create: (input: CreateGrantRequest) => Promise<boolean | undefined>; cancel: () => void }) {
  const { t } = useI18n();
  const [name, setName] = useState(initial?.name ?? '');
  const [selected, setSelected] = useState<Scope[]>(() => [...(initial?.scopes ?? available)]);
  const [libraryScope, setLibraryScope] = useState<'all' | 'selected'>(initial?.libraryScope ?? 'all');
  const [libraryIds, setLibraryIds] = useState<string[]>(initial?.libraryIds ?? []);
  const [lifetimeDays, setLifetime] = useState<30 | 90 | 365 | null | 'keep'>(initial ? 'keep' : 90);
  function submit(event: FormEvent) {
    event.preventDefault();
    void create({ name: name.trim(), libraryScope, libraryIds: libraryScope === 'all' ? [] : libraryIds, scopes: selected, ...(lifetimeDays === 'keep' ? {} : { lifetimeDays }) });
  }
  return <form className={panel} onSubmit={submit}>
    <h3 className="mb-6 flex items-center gap-2 font-semibold"><KeyRound size={20} />{t(initial ? '修改自动化授权' : '创建自动化授权')}</h3>
    <div className="grid items-start gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(160px,220px)]">
      <label className="grid min-w-0 gap-2 text-sm font-medium">{t('授权名称')}<input required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} className={`${input} h-11`} /></label>
      <div className="grid min-w-0 gap-2 text-sm font-medium"><span>{t('有效期')}</span><Select ariaLabel="有效期" className="w-full" value={String(lifetimeDays)}
        options={[...(initial ? [{ value: 'keep', label: '保持原到期时间' }] : []), { value: '30', label: '30 天' }, { value: '90', label: '90 天' }, { value: '365', label: '365 天' }, { value: 'null', label: '长期' }]}
        onChange={(selected) => { if (selected === 'keep') { setLifetime('keep'); return; } if (selected === 'null') { setLifetime(null); return; } const value = Number(selected); if (value === 30 || value === 90 || value === 365) setLifetime(value); }} />
      </div>
    </div>
    {initial ? <p className="mt-3 text-xs text-[#77716A]">{t('修改后原授权码继续有效；选择天数时，有效期从保存时重新计算。')}</p> : null}
    <fieldset className="mt-6"><legend className="mb-3 text-sm font-medium">{t('授权书库')}</legend>
      <div className="mb-3 grid gap-3 text-sm sm:grid-cols-2">{(['all', 'selected'] as const).map((scope) => <label key={scope} className={`flex min-h-11 cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 ${libraryScope === scope ? 'border-[var(--visual-color-app-brand-accent)] bg-[var(--visual-color-app-accent-softer)]' : 'border-[var(--visual-color-app-divider-strong)]'}`}><input className={choiceControl} type="radio" name="libraryScope" value={scope} checked={libraryScope === scope} onChange={() => setLibraryScope(scope)} />{t(scope === 'all' ? '全部书库（动态）' : '指定书库')}</label>)}</div>
      {libraryScope === 'selected' ? libraries.length ? <div className="grid gap-3 sm:grid-cols-2">{libraries.map((library) => <label className="flex min-h-11 min-w-0 items-center gap-3 text-sm" key={library.id}>
        <input className={choiceControl} type="checkbox" checked={libraryIds.includes(library.id)} onChange={(event) => setLibraryIds(event.target.checked ? [...libraryIds, library.id] : libraryIds.filter((id) => id !== library.id))} /><span className="min-w-0 break-words" data-i18n-skip>{library.name}</span>
      </label>)}</div> : <p className="text-sm text-[#77716A]">{t('没有可授权的书库。')}</p> : null}
      <p className="mt-3 text-xs text-[#77716A]">{t(libraryScope === 'all' ? '自动包含当前及以后可访问的书库；失去访问权限后立即移除。' : '只授权所选书库；以后新增的书库不会自动加入。')}</p>
    </fieldset>
    <fieldset className="mt-6"><legend className="mb-3 text-sm font-medium">{t('授权能力')}</legend><ScopeChoices selected={selected} available={available} change={setSelected} /></fieldset>
    <p className="mt-4 text-sm text-[#77716A]">{t('更新图书元数据仅修改系统记录；原文件写回、移动、删除和替换需要修改图书文件权限。')}</p>
    <p className="mt-3 text-sm text-[#77716A]">{t('附件上传要求客户端能读取原始文件字节。仅提供附件链接或缩略图的客户端暂不支持。封面更新只影响图书展示，不修改原文件。')}</p>
    <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-[var(--visual-color-app-divider-strong)] pt-5"><Button type="submit" loading={busy} disabled={!name.trim() || (libraryScope === 'selected' && libraryIds.length === 0)}>{t(initial ? '保存修改' : '创建授权')}</Button><Button variant="secondary" disabled={busy} onClick={cancel}>{t('取消')}</Button></div>
  </form>;
}

function ConfigurationPanel({ grant, endpoint, close }: { grant: GrantView; endpoint: string; close: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [client, setClient] = useState<McpClient>('codex');
  const [token, setToken] = useState<string>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    const controller = new AbortController();
    let expiry: number;
    function checkExpiry() {
      if (grant.expiresAtMs === null) return;
      const remaining = grant.expiresAtMs - Date.now();
      if (remaining <= 0) { controller.abort(); setToken(undefined); setError('GRANT_INACTIVE'); }
      else expiry = window.setTimeout(checkExpiry, Math.min(remaining, 2_147_483_647));
    }
    checkExpiry();
    void Promise.resolve().then(async () => {
      if (controller.signal.aborted) return;
      const value = await revealGrant(grant.id, controller.signal);
      if (!controller.signal.aborted) setToken(value);
    })
      .catch((error: unknown) => { if (!controller.signal.aborted) { setError(error instanceof Error ? error.message : 'AUTOMATION_REQUEST_FAILED'); toast.error('配置读取失败', '请关闭配置后重试'); } });
    return () => { controller.abort(); window.clearTimeout(expiry); };
  }, [grant.id, grant.expiresAtMs, toast]);
  const template = token ? clientTemplate(endpoint, token, client) : '';
  async function copy() {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(template);
      else {
        const previous = document.activeElement;
        const field = document.createElement('textarea'); field.value = template;
        field.style.position = 'fixed'; field.style.opacity = '0'; document.body.appendChild(field);
        try { field.select(); if (!document.execCommand('copy')) throw new Error('COPY_FAILED'); }
        finally { field.remove(); if (previous instanceof HTMLElement) previous.focus(); }
      }
      toast.success(t('已复制'));
    } catch { toast.error(t('复制失败，请手动复制')); }
  }
  function download() {
    let url: string | undefined;
    try {
      url = URL.createObjectURL(new Blob([template], { type: client === 'codex' ? 'text/plain' : 'application/json' }));
      const link = document.createElement('a'); link.href = url; link.download = client === 'codex' ? 'ermao-mcp.toml' : 'ermao-mcp.json'; link.click();
      toast.info('配置下载已开始');
    } catch { toast.error('配置下载失败', '请稍后重试'); }
    finally { if (url) { const downloadUrl = url; window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 0); } }
  }
  const message = error === 'TOKEN_NOT_RECOVERABLE' ? '历史令牌无法取回，请重新创建授权' : error === 'GRANT_INACTIVE' ? '授权已过期或撤销，请重新创建授权。' : ['TOKEN_KEY_UNAVAILABLE', 'TOKEN_KEY_INVALID', 'TOKEN_DECRYPTION_FAILED'].includes(error ?? '') ? '令牌密钥不可用或解密失败，请联系管理员恢复密钥。' : '配置读取失败，请关闭后重试。';
  return <section className="mt-4 rounded-xl border border-[#E2DED8] p-4" aria-label={t('授权配置')}>
    <div className="flex items-center justify-between gap-3"><h4 className="font-medium">{t('客户端配置')} · <span data-i18n-skip>{grant.name}</span></h4><Button variant="ghost" onClick={close}>{t('关闭配置')}</Button></div>
    <Select ariaLabel="AI 客户端" className="mt-3" value={client} options={[{ value: 'codex', label: 'Codex' }, { value: 'lm-studio', label: 'LM Studio' }, { value: 'cursor', label: 'Cursor' }]} onChange={(value) => { if (value === 'codex' || value === 'lm-studio' || value === 'cursor') setClient(value); }} />
    <p className="mt-3 text-sm text-[#77716A]">{t(client === 'codex' ? '将此配置合并到 Codex 的 config.toml。' : '将此配置合并到客户端的 mcp.json。')}</p>
    {error ? <p role="alert" className="mt-3 text-sm text-red-700">{t(message)}</p> : !token ? <p role="status" className="mt-3 text-sm">{t('正在读取授权配置…')}</p> : <>
      <p className="mt-3 text-xs text-[#77716A]">{t('配置包含此授权的完整令牌，请勿分享或提交到仓库。')}</p>
      <pre className="mt-3 overflow-x-auto rounded-xl bg-[#F7F5F2] p-4 text-xs leading-6" data-i18n-skip>{template}</pre>
      <div className="mt-3 flex flex-wrap gap-2"><Button icon={Copy} variant="secondary" disabled={!endpoint} onClick={() => void copy()}>{t('复制配置')}</Button><Button icon={Download} variant="secondary" disabled={!endpoint} onClick={download}>{t('下载配置')}</Button></div>
    </>}
    {!endpoint ? <p className="mt-3 text-sm">{t('管理员尚未配置公开 URL。')}</p> : null}
  </section>;
}

function GrantsPanel({ automation, canManage, admin, openService }: { automation: ReturnType<typeof useAutomation>; canManage: boolean; admin: boolean; openService: () => void }) {
  const { t, locale } = useI18n();
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string>();
  const [configurationId, setConfigurationId] = useState<string>();
  const { data, busy } = automation;
  if (!data) return null;
  const formatTime = (value: number | null) => value === null ? t('尚未使用') : new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(value);
  return <div className="space-y-5">
    <div className="flex items-center justify-between gap-3"><h3 className="font-semibold">{t('我的授权')}</h3><Button disabled={!data.settings.enabled && !admin} onClick={() => { if (!data.settings.enabled) openService(); else { setEditingId(undefined); setConfigurationId(undefined); setCreating(true); } }}>{t(data.settings.enabled ? '创建授权' : '请先开启 MCP 服务')}</Button></div>
    {!data.settings.enabled && !admin ? <p className="text-sm text-[#77716A]">{t('请联系管理员开启 MCP 服务后创建授权。')}</p> : null}
    {creating && data.settings.enabled ? <GrantForm libraries={data.libraries} available={data.settings.enabledScopes.filter((scope) => canManage || scope === 'system:read' || scope === 'shelves:write')} busy={busy} cancel={() => setCreating(false)} create={async (input) => { const success = await automation.create(input); if (success) setCreating(false); return success; }} /> : null}
    <section className={panel} aria-label={t('授权列表')}>
      {data.grants.length === 0 ? <p className="text-sm text-[#77716A]">{t('尚未创建自动化授权。')}</p> : <ul className="divide-y divide-[#E2DED8]">{data.grants.map((grant) => {
        const active = grant.revokedAtMs === null && (grant.expiresAtMs === null || grant.expiresAtMs > Date.now());
        return <li key={grant.id} className="py-4 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h4 className="break-all font-medium" data-i18n-skip>{grant.name}</h4><p className="mt-1 text-xs text-[#77716A]">{t(grant.revokedAtMs !== null ? '已撤销' : active ? '有效' : '已过期')}</p></div>
            <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={busy || !active} onClick={() => { setCreating(false); setConfigurationId(undefined); setEditingId(editingId === grant.id ? undefined : grant.id); }}>{t('修改')}</Button><Button variant="secondary" disabled={!active || !grant.tokenAvailable} onClick={() => { setEditingId(undefined); setCreating(false); setConfigurationId(configurationId === grant.id ? undefined : grant.id); }}>{t('复制配置')}</Button><Button variant="danger" disabled={busy || grant.revokedAtMs !== null} onClick={() => { setConfigurationId(undefined); setEditingId(undefined); void automation.revoke(grant.id); }}>{t('撤销授权')}</Button></div></div>
          <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
            <div><dt className="text-[#77716A]">{t('授权书库')}</dt><dd className="mt-1 break-all" data-i18n-skip>{grant.libraryScope === 'all' ? t('全部书库（动态）') : (grant.libraryIds ?? []).map((id) => data.libraries.find((library) => library.id === id)?.name ?? id).join(' · ')}</dd></div>
            <div><dt className="text-[#77716A]">{t('授权能力')}</dt><dd className="mt-1">{(grant.scopes ?? []).map((scope) => t(scopeLabels[scope])).join(' · ')}</dd></div>
            <div><dt className="text-[#77716A]">{t('到期时间')}</dt><dd className="mt-1">{grant.expiresAtMs === null ? t('长期') : formatTime(grant.expiresAtMs)}</dd></div>
            <div><dt className="text-[#77716A]">{t('最近使用')}</dt><dd className="mt-1">{formatTime(grant.lastUsedAtMs)}</dd></div>
          </dl>
          {active && editingId === grant.id ? <div className="mt-4"><GrantForm key={grant.id} initial={grant}
            libraries={[...data.libraries, ...(grant.libraryIds ?? []).filter((id) => !data.libraries.some((library) => library.id === id)).map((id) => ({ id, name: id }))]}
            available={Array.from(new Set([...data.settings.enabledScopes.filter((scope) => canManage || scope === 'system:read' || scope === 'shelves:write'), ...(grant.scopes ?? [])]))}
            busy={busy} cancel={() => setEditingId(undefined)} create={async (input) => { const success = await automation.update(grant.id, input); if (success) setEditingId(undefined); return success; }} /></div> : null}
          {active && !grant.tokenAvailable ? <p className="mt-3 text-sm text-[#77716A]">{t('历史令牌无法取回，请重新创建授权')}</p> : null}
          {active && grant.tokenAvailable && configurationId === grant.id ? <ConfigurationPanel key={grant.id} grant={grant} endpoint={connectionUrl(data.settings)} close={() => setConfigurationId(undefined)} /> : null}
        </li>;
      })}</ul>}
    </section>
  </div>;
}

export function AutomationSettingsPage() {
  const session = useAppSession();
  const { t, locale } = useI18n();
  const router = useRouter();
  const search = useSearchParams();
  const requestedTab = search.get('tab');
  const tab = requestedTab === 'service' || requestedTab === 'operations' ? requestedTab : 'grants';
  const state = useAutomation(session?.user?.id);
  const toast = useToast();
  async function feedback(result: Promise<boolean | undefined>, success: string, failure: string) {
    const completed = await result;
    if (completed === true) toast.success(success);
    else if (completed === false) toast.error(failure, '自动化请求未完成，请检查权限和配置后重试。');
    return completed;
  }
  const automation = {
    ...state,
    retry: () => feedback(state.retry(), '自动化配置已重新读取', '重新读取自动化配置失败'),
    save: (settings: ServiceSettings) => feedback(state.save(settings), 'MCP 服务设置已保存', '保存服务设置失败'),
    create: (input: CreateGrantRequest) => feedback(state.create(input), '授权已创建', '创建授权失败'),
    update: (id: string, input: UpdateGrantRequest) => feedback(state.update(id, input), '授权已修改', '修改授权失败'),
    revoke: (id: string) => feedback(state.revoke(id), '授权已撤销', '撤销授权失败'),
    refreshOperations: () => feedback(state.refreshOperations(), '任务列表已刷新', '刷新任务失败'),
    cancel: (id: string) => feedback(state.cancel(id), '已请求取消任务', '取消任务失败')
  };
  const { data, busy } = automation;
  const formatTime = (value: number | null) => value === null ? t('尚未使用') : new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(value);
  const tabs = [{ key: 'service', label: 'MCP 服务' }, { key: 'grants', label: '授权服务' }, { key: 'operations', label: '操作列表' }].map((item) => ({ ...item, href: `/settings/automation?tab=${item.key}` }));
  return <SettingsCenterShell title="自动化授权" description="连接你自己的 AI 客户端，分别授权书库查询、元数据整理和文件操作。">
    <div className="max-w-[960px] space-y-5">
      <SettingsTabs tabs={tabs} active={tab} />
      {automation.error ? <div role="alert" className={`${panel} text-red-700`}><p>{t('自动化请求未完成，请检查权限和配置后重试。')}</p><Button variant="secondary" className="mt-3" loading={busy} onClick={() => void automation.retry()}>{t('重新读取')}</Button></div> : null}
      {!data && !automation.error ? <p role="status">{t('正在读取自动化配置…')}</p> : null}
      {data ? <>
        <div role="status" className="flex flex-wrap items-center justify-between gap-3 text-sm"><span>{t(data.settings.enabled ? 'MCP 服务已开启' : 'MCP 服务已关闭')}</span><span className="text-[#77716A]">{t('仅支持手动 Bearer Token，不提供 OAuth 登录。')}</span></div>
        {tab === 'service' ? session?.authorization?.isAdmin ? <ServiceForm key={JSON.stringify(data.settings)} settings={data.settings} busy={busy} save={automation.save} /> : <p>{t('请联系管理员管理 MCP 服务设置。')}</p> : null}
        {tab === 'grants' ? <GrantsPanel key={session?.user?.id} automation={automation} admin={!!session?.authorization?.isAdmin} canManage={!!session?.authorization?.canManageSystem} openService={() => router.push('/settings/automation?tab=service')} /> : null}
        {tab === 'operations' ? <>
        <section className={panel} aria-labelledby="automation-operations-title">
          <div className="flex items-center justify-between gap-3"><h3 id="automation-operations-title" className="font-semibold">{t('最近的文件任务')}</h3><Button variant="secondary" disabled={busy} onClick={() => void automation.refreshOperations()}>{t('刷新任务')}</Button></div>
          <p className="mt-2 text-sm text-[#77716A]">{t('显示当前权限内最近 50 项任务。已接收不代表已完成；取消只影响尚未开始的文件操作。')}</p>
          {data.operations.length === 0 ? <p className="mt-3 text-sm text-[#77716A]">{t('暂无文件任务。')}</p> : <ul className="mt-3 divide-y divide-[#E2DED8]">{data.operations.map((operation) => <li key={operation.operation_id} className="py-4">
            <div className="flex items-start justify-between gap-3"><div><h4 className="font-medium">{t(operation.kind === 'file_delete' ? '永久删除图书文件' : operation.kind === 'file_replace' ? '替换图书文件' : operation.kind === 'file_move' ? '移动和整理文件' : operation.kind === 'book_upload' ? '上传图书附件' : operation.kind === 'cover_upload' ? '更新图书展示封面' : '写回文件元数据')} · {t(operation.kind === 'book_upload' && operation.status === 'QUEUED' ? '等待导入' : operationStatusLabel(operation.status))}</h4><p className="mt-1 text-xs text-[#77716A]">{formatTime(operation.created_at_ms)} · {new Intl.NumberFormat(locale).format(operation.total_targets)} {t('个文件目标')}</p></div>
              {canCancelOperation(operation.status, operation.kind) ? <Button variant="secondary" disabled={busy || operation.cancel_requested} onClick={() => void automation.cancel(operation.operation_id)}>{t(operation.cancel_requested ? '已请求取消' : '取消任务')}</Button> : null}</div>
            {operation.kind === 'book_upload' && operation.file_saved ? <p className="mt-2 text-xs">{t('原文件已保存；导入失败也不会删除原文件。')}</p> : null}
            {operation.received_bytes != null && operation.size_bytes != null ? <p className="mt-2 text-xs">{t('附件传输字节数')} <span data-i18n-skip>{new Intl.NumberFormat(locale).format(operation.received_bytes)} / {new Intl.NumberFormat(locale).format(operation.size_bytes)}</span></p> : null}
            <p className="mt-2 break-all text-xs text-[#77716A]" data-i18n-skip>{operation.operation_id}</p>
            {operation.status === 'RECOVERY_REQUIRED' ? <p role="alert" className="mt-2 text-sm text-amber-800">{t('任务未完成，需要核对文件和书库记录。请保留任务标识，不要重复提交相同操作。')}</p> : null}
            <details className="mt-3 text-sm"><summary className="cursor-pointer">{t('查看逐项结果（最多 50 项）')}</summary><ul className="mt-2 space-y-2">{operation.targets.map((target, index) => <li key={`${target.relative_path}:${index}`} className="rounded-lg bg-[#F7F5F2] p-3">
              <p className="break-all" data-i18n-skip>{target.relative_path}{target.destination_relative_path ? ` → ${target.destination_relative_path}` : ''}</p><p className="mt-1 text-xs">{t(operationStatusLabel(target.stage))}{target.error_code ? <span data-i18n-skip>{` · ${target.error_code}`}</span> : null}</p>
            </li>)}</ul></details>
          </li>)}</ul>}
        </section>
        </> : null}
      </> : null}
    </div>
  </SettingsCenterShell>;
}

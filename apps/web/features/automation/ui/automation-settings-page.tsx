'use client';

import { Copy, Download, KeyRound, ShieldCheck } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAppSession } from '../../../components/layout/app-session-context';
import { Button } from '../../../components/ui/button';
import { Select } from '../../../components/ui/select';
import { useToast } from '../../../components/ui/feedback';
import { useI18n } from '../../../i18n/provider';
import type { CreateGrantRequest, GrantView, Scope } from '../../../generated/automation';
import { SettingsCenterShell, SettingsTabs } from '../../settings/public';
import { revealGrant } from '../api/client';
import { useAutomation } from '../application/use-automation';
import { canCancelOperation, operationStatusLabel, clientTemplate, connectionUrl, scopeLabels, scopes, selectedScopes, type LibraryChoice, type ServiceSettings, type McpClient } from '../model/configuration';

const panel = 'rounded-[20px] border border-[var(--visual-color-app-divider-strong)] bg-[var(--visual-color-app-surface-raised)] p-5';
const input = 'w-full rounded-xl border border-[var(--visual-color-app-divider-strong)] bg-white px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--visual-color-app-focus-ring)]';

function ScopeChoices({ selected, available, change }: { selected: Scope[]; available: Scope[]; change: (next: Scope[]) => void }) {
  const { t } = useI18n();
  const groups: { label: string; scopes: Scope[] }[] = [
    { label: '基础查询与书架', scopes: ['library:read', 'shelves:write'] },
    { label: '系统元数据', scopes: ['tags:write', 'metadata:write', 'metadata:override'] },
    { label: '源文件操作', scopes: ['files:read', 'files:move', 'metadata:writeback'] }
  ];
  return <div className="space-y-4">{groups.map((group) => {
    const visible = group.scopes.filter((scope) => available.includes(scope));
    return visible.length ? <fieldset key={group.label}><legend className="mb-2 text-xs text-[#77716A]">{t(group.label)}</legend><div className="grid gap-3 sm:grid-cols-2">{visible.map((scope) => <label key={scope} className="flex items-center gap-3 text-sm">
      <input type="checkbox" checked={selected.includes(scope)} disabled={scope === 'library:read'} onChange={(event) => change(selectedScopes(selected, scope, event.target.checked))} className="h-4 w-4 accent-[#EF4D2F]" />
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

function GrantForm({ libraries, available, busy, create, cancel }: { libraries: LibraryChoice[]; available: Scope[]; busy: boolean; create: (input: CreateGrantRequest) => Promise<boolean | undefined>; cancel: () => void }) {
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [selected, setSelected] = useState<Scope[]>(['library:read']);
  const [libraryScope, setLibraryScope] = useState<'all' | 'selected'>('all');
  const [libraryIds, setLibraryIds] = useState<string[]>([]);
  const [lifetimeDays, setLifetime] = useState<30 | 90 | 365>(90);
  const [sidecar, setSidecar] = useState(true);
  const [embedded, setEmbedded] = useState(false);
  const [crossLibrary, setCrossLibrary] = useState(false);
  const canWriteback = selected.includes('metadata:writeback');
  function submit(event: FormEvent) {
    event.preventDefault();
    void create({ name: name.trim(), libraryScope, libraryIds: libraryScope === 'all' ? [] : libraryIds, scopes: selected, lifetimeDays,
      writebackTargets: canWriteback ? [...(sidecar ? ['sidecar' as const] : []), ...(embedded ? ['embedded' as const] : [])] : [],
      allowCrossLibrary: selected.includes('files:move') && crossLibrary });
  }
  return <form className={panel} onSubmit={submit}>
    <h3 className="mb-4 flex items-center gap-2 font-semibold"><KeyRound size={20} />{t('创建自动化授权')}</h3>
    <div className="grid gap-4 sm:grid-cols-2">
      <label className="text-sm">{t('授权名称')}<input required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} className={`${input} mt-2`} /></label>
      <div className="text-sm">{t('有效期')}<Select ariaLabel="有效期" className="mt-2" value={String(lifetimeDays)}
        options={[{ value: '30', label: '30 天' }, { value: '90', label: '90 天' }, { value: '365', label: '365 天' }]}
        onChange={(selected) => { const value = Number(selected); if (value === 30 || value === 90 || value === 365) setLifetime(value); }} />
      </div>
    </div>
    <fieldset className="mt-5"><legend className="mb-3 text-sm font-medium">{t('授权书库')}</legend>
      <div className="mb-4 flex flex-wrap gap-4 text-sm">{(['all', 'selected'] as const).map((scope) => <label key={scope} className="flex items-center gap-2"><input type="radio" name="libraryScope" value={scope} checked={libraryScope === scope} onChange={() => setLibraryScope(scope)} />{t(scope === 'all' ? '全部书库（动态）' : '指定书库')}</label>)}</div>
      {libraryScope === 'selected' ? libraries.length ? <div className="grid gap-3 sm:grid-cols-2">{libraries.map((library) => <label className="flex items-center gap-3 text-sm" key={library.id}>
        <input type="checkbox" checked={libraryIds.includes(library.id)} onChange={(event) => setLibraryIds(event.target.checked ? [...libraryIds, library.id] : libraryIds.filter((id) => id !== library.id))} /><span data-i18n-skip>{library.name}</span>
      </label>)}</div> : <p className="text-sm text-[#77716A]">{t('没有可授权的书库。')}</p> : null}
      <p className="mt-3 text-xs text-[#77716A]">{t(libraryScope === 'all' ? '自动包含当前及以后可访问的书库；失去访问权限后立即移除。' : '只授权所选书库；以后新增的书库不会自动加入。')}</p>
    </fieldset>
    <fieldset className="mt-5"><legend className="mb-3 text-sm font-medium">{t('授权能力')}</legend><ScopeChoices selected={selected} available={available} change={setSelected} /></fieldset>
    <p className="mt-4 text-sm text-[#77716A]">{t('更新系统元数据不会改动文件；写回文件与覆盖人工保护字段需要分别授权。')}</p>
    {canWriteback ? <fieldset className="mt-4 space-y-3 rounded-xl bg-[#FFF4EF] p-4 text-sm"><legend className="px-1 font-medium">{t('允许写入的文件')}</legend>
      <label className="flex gap-3"><input type="checkbox" checked={sidecar} onChange={(event) => setSidecar(event.target.checked)} />{t('OPF / ComicInfo 伴随文件')}</label>
      <label className="flex gap-3"><input type="checkbox" checked={embedded} onChange={(event) => setEmbedded(event.target.checked)} />{t('EPUB / 漫画包 / 音频 / PDF 原文件')}</label>
      <p>{t('文件操作先生成方案，再执行。发生冲突或无法保真写入时会拒绝修改。')}</p>
    </fieldset> : null}
    {selected.includes('files:move') ? <label className="mt-4 flex gap-3 text-sm"><input type="checkbox" checked={crossLibrary} onChange={(event) => setCrossLibrary(event.target.checked)} />{t('允许在所选书库之间移动完整图书')}</label> : null}
    <Button className="mt-5" type="submit" loading={busy} disabled={!name.trim() || (libraryScope === 'selected' && libraryIds.length === 0) || (canWriteback && !sidecar && !embedded)}>{t('创建授权')}</Button><Button className="ml-2 mt-5" variant="secondary" onClick={cancel}>{t('取消')}</Button>
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
  const [configurationId, setConfigurationId] = useState<string>();
  const { data, busy } = automation;
  if (!data) return null;
  const formatTime = (value: number | null) => value === null ? t('尚未使用') : new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(value);
  return <div className="space-y-5">
    <div className="flex items-center justify-between gap-3"><h3 className="font-semibold">{t('我的授权')}</h3><Button disabled={!data.settings.enabled && !admin} onClick={() => { if (!data.settings.enabled) openService(); else setCreating(true); }}>{t(data.settings.enabled ? '创建授权' : '请先开启 MCP 服务')}</Button></div>
    {!data.settings.enabled && !admin ? <p className="text-sm text-[#77716A]">{t('请联系管理员开启 MCP 服务后创建授权。')}</p> : null}
    {creating && data.settings.enabled ? <GrantForm libraries={data.libraries} available={data.settings.enabledScopes.filter((scope) => canManage || scope === 'library:read' || scope === 'shelves:write')} busy={busy} cancel={() => setCreating(false)} create={async (input) => { const success = await automation.create(input); if (success) setCreating(false); return success; }} /> : null}
    <section className={panel} aria-label={t('授权列表')}>
      {data.grants.length === 0 ? <p className="text-sm text-[#77716A]">{t('尚未创建自动化授权。')}</p> : <ul className="divide-y divide-[#E2DED8]">{data.grants.map((grant) => {
        const active = grant.revokedAtMs === null && grant.expiresAtMs > Date.now();
        return <li key={grant.id} className="py-4 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h4 className="break-all font-medium" data-i18n-skip>{grant.name}</h4><p className="mt-1 text-xs text-[#77716A]">{t(grant.revokedAtMs !== null ? '已撤销' : active ? '有效' : '已过期')}</p></div>
            <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={!active || !grant.tokenAvailable} onClick={() => setConfigurationId(configurationId === grant.id ? undefined : grant.id)}>{t('复制配置')}</Button><Button variant="danger" disabled={busy || grant.revokedAtMs !== null} onClick={() => { setConfigurationId(undefined); void automation.revoke(grant.id); }}>{t('撤销授权')}</Button></div></div>
          <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
            <div><dt className="text-[#77716A]">{t('授权书库')}</dt><dd className="mt-1 break-all" data-i18n-skip>{grant.libraryScope === 'all' ? t('全部书库（动态）') : (grant.libraryIds ?? []).map((id) => data.libraries.find((library) => library.id === id)?.name ?? id).join(' · ')}</dd></div>
            <div><dt className="text-[#77716A]">{t('授权能力')}</dt><dd className="mt-1">{(grant.scopes ?? []).map((scope) => t(scopeLabels[scope])).join(' · ')}</dd></div>
            <div><dt className="text-[#77716A]">{t('到期时间')}</dt><dd className="mt-1">{formatTime(grant.expiresAtMs)}</dd></div>
            <div><dt className="text-[#77716A]">{t('最近使用')}</dt><dd className="mt-1">{formatTime(grant.lastUsedAtMs)}</dd></div>
          </dl>
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
          <p className="mt-2 text-sm text-[#77716A]">{t('显示当前权限内最近 50 项任务。已接收不代表已完成；取消只影响尚未发布的文件。')}</p>
          {data.operations.length === 0 ? <p className="mt-3 text-sm text-[#77716A]">{t('暂无文件任务。')}</p> : <ul className="mt-3 divide-y divide-[#E2DED8]">{data.operations.map((operation) => <li key={operation.operation_id} className="py-4">
            <div className="flex items-start justify-between gap-3"><div><h4 className="font-medium">{t(operation.kind === 'file_move' ? '移动和整理文件' : '写回文件元数据')} · {t(operationStatusLabel(operation.status))}</h4><p className="mt-1 text-xs text-[#77716A]">{formatTime(operation.created_at_ms)} · {new Intl.NumberFormat(locale).format(operation.total_targets)} {t('个文件目标')}</p></div>
              {canCancelOperation(operation.status) ? <Button variant="secondary" disabled={busy || operation.cancel_requested} onClick={() => void automation.cancel(operation.operation_id)}>{t(operation.cancel_requested ? '已请求取消' : '取消任务')}</Button> : null}</div>
            <p className="mt-2 break-all text-xs text-[#77716A]" data-i18n-skip>{operation.operation_id}</p>
            {operation.status === 'RECOVERY_REQUIRED' ? <p role="alert" className="mt-2 text-sm text-amber-800">{t('文件已保留，任务需要核对恢复。请保留任务标识和备份，不要重复提交相同文件。')}</p> : null}
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

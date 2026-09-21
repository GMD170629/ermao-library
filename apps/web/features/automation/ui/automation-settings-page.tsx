'use client';

import { Copy, Download, KeyRound, ShieldCheck } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { useAppSession } from '../../../components/layout/app-session-context';
import { Button } from '../../../components/ui/button';
import { Select } from '../../../components/ui/select';
import { useToast } from '../../../components/ui/feedback';
import { useI18n } from '../../../i18n/provider';
import type { CreateGrantRequest, Scope } from '../../../generated/automation';
import { SettingsCenterShell } from '../../settings/public';
import { useAutomation } from '../application/use-automation';
import { canCancelOperation, operationStatusLabel, clientTemplate, connectionUrl, scopeLabels, scopes, selectedScopes, type LibraryChoice, type ServiceSettings } from '../model/configuration';

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

function ServiceForm({ settings, busy, save }: { settings: ServiceSettings; busy: boolean; save: (value: ServiceSettings) => Promise<void> }) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(settings);
  return <form className={panel} onSubmit={(event) => { event.preventDefault(); void save(draft); }}>
    <h3 className="mb-3 flex items-center gap-2 font-semibold"><ShieldCheck size={20} />{t('MCP 服务')}</h3>
    <label className="flex items-center gap-3 text-sm"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} />{t('启用 MCP 服务')}</label>
    <p className="mt-2 text-sm text-[#77716A]">{t('关闭后，客户端不能继续调用；已经发布的文件只完成必要的一致性修复。')}</p>
    <label className="mt-4 block text-sm">{t('公开 URL')}<input type="url" required={draft.enabled} className={`${input} mt-2`} value={draft.publicBaseUrl} onChange={(event) => setDraft({ ...draft, publicBaseUrl: event.target.value })} placeholder="https://books.example.com/books" data-i18n-skip /></label>
    <p className="mt-2 text-xs text-[#77716A]">{t('填写网站根地址，包含部署前缀；系统会自动添加 /api/mcp。')}</p>
    <fieldset className="mt-5"><legend className="mb-3 text-sm font-medium">{t('允许用户授权的能力')}</legend><ScopeChoices selected={draft.enabledScopes} available={scopes} change={(enabledScopes) => setDraft({ ...draft, enabledScopes })} /></fieldset>
    <label className="mt-5 flex items-start gap-3 text-sm"><input type="checkbox" checked={draft.allowInsecureHttp} onChange={(event) => setDraft({ ...draft, allowInsecureHttp: event.target.checked })} />{t('允许受信任局域网使用 HTTP（令牌将明文传输）')}</label>
    <Button className="mt-5" type="submit" loading={busy}>{t('保存服务设置')}</Button>
  </form>;
}

function GrantForm({ libraries, available, busy, create }: { libraries: LibraryChoice[]; available: Scope[]; busy: boolean; create: (input: CreateGrantRequest) => Promise<void> }) {
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [selected, setSelected] = useState<Scope[]>(['library:read']);
  const [libraryIds, setLibraryIds] = useState<string[]>([]);
  const [lifetimeDays, setLifetime] = useState<30 | 90 | 365>(90);
  const [sidecar, setSidecar] = useState(true);
  const [embedded, setEmbedded] = useState(false);
  const [crossLibrary, setCrossLibrary] = useState(false);
  const canWriteback = selected.includes('metadata:writeback');
  function submit(event: FormEvent) {
    event.preventDefault();
    void create({ name: name.trim(), libraryIds, scopes: selected, lifetimeDays,
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
      {libraries.length ? <div className="grid gap-3 sm:grid-cols-2">{libraries.map((library) => <label className="flex items-center gap-3 text-sm" key={library.id}>
        <input type="checkbox" checked={libraryIds.includes(library.id)} onChange={(event) => setLibraryIds(event.target.checked ? [...libraryIds, library.id] : libraryIds.filter((id) => id !== library.id))} /><span data-i18n-skip>{library.name}</span>
      </label>)}</div> : <p className="text-sm text-[#77716A]">{t('没有可授权的书库。')}</p>}
      <p className="mt-3 text-xs text-[#77716A]">{t('授权范围固定；以后新增的书库不会自动加入。')}</p>
    </fieldset>
    <fieldset className="mt-5"><legend className="mb-3 text-sm font-medium">{t('授权能力')}</legend><ScopeChoices selected={selected} available={available} change={setSelected} /></fieldset>
    <p className="mt-4 text-sm text-[#77716A]">{t('更新系统元数据不会改动文件；写回文件与覆盖人工保护字段需要分别授权。')}</p>
    {canWriteback ? <fieldset className="mt-4 space-y-3 rounded-xl bg-[#FFF4EF] p-4 text-sm"><legend className="px-1 font-medium">{t('允许写入的文件')}</legend>
      <label className="flex gap-3"><input type="checkbox" checked={sidecar} onChange={(event) => setSidecar(event.target.checked)} />{t('OPF / ComicInfo 伴随文件')}</label>
      <label className="flex gap-3"><input type="checkbox" checked={embedded} onChange={(event) => setEmbedded(event.target.checked)} />{t('EPUB / 漫画包 / 音频 / PDF 原文件')}</label>
      <p>{t('文件操作先生成方案，再执行。发生冲突或无法保真写入时会拒绝修改。')}</p>
    </fieldset> : null}
    {selected.includes('files:move') ? <label className="mt-4 flex gap-3 text-sm"><input type="checkbox" checked={crossLibrary} onChange={(event) => setCrossLibrary(event.target.checked)} />{t('允许在所选书库之间移动完整图书')}</label> : null}
    <Button className="mt-5" type="submit" loading={busy} disabled={!name.trim() || libraryIds.length === 0 || (canWriteback && !sidecar && !embedded)}>{t('创建授权并显示令牌')}</Button>
  </form>;
}

export function AutomationSettingsPage() {
  const session = useAppSession();
  const { t, locale } = useI18n();
  const toast = useToast();
  const automation = useAutomation(session?.user?.id);
  const { data, created, busy } = automation;
  const [includeToken, setIncludeToken] = useState<string>();
  const endpoint = data ? connectionUrl(data.settings) : '';
  const template = clientTemplate(endpoint, includeToken === created?.grant.id ? created?.token : undefined);
  const formatTime = (value: number | null) => value === null ? t('尚未使用') : new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(value);
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); toast.success(t('已复制')); }
    catch { toast.error(t('复制失败，请手动复制')); }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([template], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = 'ermao-mcp.json'; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }
  return <SettingsCenterShell title="自动化授权" description="连接你自己的 AI 客户端，分别授权书库查询、元数据整理和文件操作。">
    <div className="max-w-[960px] space-y-5">
      {automation.error ? <div role="alert" className={`${panel} text-red-700`}><p>{t('自动化请求未完成，请检查权限和配置后重试。')}</p><Button variant="secondary" className="mt-3" onClick={automation.retry}>{t('重新读取')}</Button></div> : null}
      {!data && !automation.error ? <p role="status">{t('正在读取自动化配置…')}</p> : null}
      {data ? <>
        <div role="status" className="flex flex-wrap items-center justify-between gap-3 text-sm"><span>{t(data.settings.enabled ? 'MCP 服务已开启' : 'MCP 服务已关闭')}</span><span className="text-[#77716A]">{t('仅支持手动 Bearer Token，不提供 OAuth 登录。')}</span></div>
        {session?.authorization?.isAdmin ? <ServiceForm key={JSON.stringify(data.settings)} settings={data.settings} busy={busy} save={automation.save} /> : null}
        <GrantForm key={`${session?.authorization?.canManageSystem}:${data.settings.enabledScopes.join(',')}`} libraries={data.libraries} available={data.settings.enabledScopes.filter((scope) => session?.authorization?.canManageSystem || scope === 'library:read' || scope === 'shelves:write')} busy={busy} create={automation.create} />
        {created ? <section className={`${panel} border-[#EF4D2F]`} aria-labelledby="new-token-title"><h3 id="new-token-title" className="font-semibold">{t('令牌仅显示这一次')}</h3>
          <p className="mt-2 text-sm text-[#77716A]">{t('请保存到可信客户端。关闭或刷新后无法再次查看；丢失时请撤销并重新创建。')}</p>
          <div className="mt-3 flex gap-2"><input className={input} readOnly value={created.token} aria-label={t('新建的自动化令牌')} data-i18n-skip /><Button icon={Copy} variant="secondary" onClick={() => void copy(created.token)}>{t('复制令牌')}</Button></div>
          <Button variant="ghost" className="mt-3" onClick={() => { setIncludeToken(undefined); automation.dismissToken(); }}>{t('我已保存，关闭令牌')}</Button>
        </section> : null}
        <section className={panel} aria-labelledby="automation-template-title"><h3 id="automation-template-title" className="font-semibold">{t('LM Studio / Cursor 配置模板')}</h3>
          <p className="mt-2 text-sm text-[#77716A]">{t('在客户端的 mcp.json 中合并此配置，再选择支持工具调用的模型。LM Studio 可使用本地模型；Cursor 不保证本地推理。')}</p>
          <p className="mt-2 break-all text-sm" data-i18n-skip>{endpoint || t('管理员尚未配置公开 URL。')}</p>
          {created ? <label className="mt-4 flex items-start gap-3 text-sm"><input type="checkbox" checked={includeToken === created.grant.id} onChange={(event) => setIncludeToken(event.target.checked ? created.grant.id : undefined)} />{t('在复制和下载的配置中包含本次令牌（请勿分享或提交到仓库）')}</label> : null}
          <pre className="mt-4 overflow-x-auto rounded-xl bg-[#F7F5F2] p-4 text-xs leading-6" data-i18n-skip>{template}</pre>
          <div className="mt-4 flex flex-wrap gap-2"><Button icon={Copy} variant="secondary" disabled={!endpoint} onClick={() => void copy(template)}>{t('复制配置')}</Button><Button icon={Download} variant="secondary" disabled={!endpoint} onClick={download}>{t('下载配置')}</Button></div>
          <details className="mt-5 text-sm"><summary className="cursor-pointer font-medium">{t('支持范围与使用说明')}</summary><div className="mt-3 space-y-2 text-[#77716A]">
            <p>{t('OPF、EPUB 和 ComicInfo 按所选字段写入；音频与 PDF 当前支持标题、作者和简介。PDF 最大 64 MiB，签名或加密文件拒绝写入。')}</p>
            <p>{t('先让客户端查询 get_context 和 get_metadata_schema；文件改动先预览方案，确认实际目标后再执行。')}</p>
            <p>{t('任务已接收不代表文件已修改。通过 get_operation 查询逐项结果，cancel_operation 取消尚未完成的项目。')}</p>
            <p><a href="https://lmstudio.ai/docs/app/mcp" target="_blank" rel="noreferrer" className="underline">LM Studio</a><span> · </span><a href="https://cursor.com/docs/mcp" target="_blank" rel="noreferrer" className="underline">Cursor</a></p>
          </div></details>
        </section>
        <section className={panel} aria-labelledby="automation-grants-title"><h3 id="automation-grants-title" className="font-semibold">{t('我的授权')}</h3>
          {data.grants.length === 0 ? <p className="mt-3 text-sm text-[#77716A]">{t('尚未创建自动化授权。')}</p> : <ul className="mt-3 divide-y divide-[#E2DED8]">{data.grants.map((grant) => <li key={grant.id} className="py-4">
            <div className="flex items-start justify-between gap-3"><div><h4 className="font-medium" data-i18n-skip>{grant.name}</h4><p className="mt-1 text-xs text-[#77716A]">{t(grant.revokedAtMs !== null ? '已撤销' : grant.expiresAtMs <= Date.now() ? '已过期' : '有效')} · {t('到期时间')} {formatTime(grant.expiresAtMs)}</p></div>
              <Button variant="danger" disabled={busy || grant.revokedAtMs !== null} onClick={() => void automation.revoke(grant.id)}>{t('撤销授权')}</Button></div>
            <p className="mt-2 text-xs text-[#77716A]">{(grant.scopes ?? []).map((scope) => t(scopeLabels[scope])).join(' · ')}</p>
            <p className="mt-2 text-xs text-[#77716A]" data-i18n-skip>{grant.libraryIds.map((id) => data.libraries.find((library) => library.id === id)?.name ?? id).join(' · ')}</p>
            <p className="mt-2 text-xs text-[#77716A]">{t('最近使用')} {formatTime(grant.lastUsedAtMs)}</p>
          </li>)}</ul>}
        </section>
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
    </div>
  </SettingsCenterShell>;
}

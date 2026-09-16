'use client';

import { AlertCircle, CheckCircle2, RefreshCw, Sparkles } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useAppSession } from '@/components/layout/app-session-context';
import { useConfirm } from '@/components/ui/feedback';
import { useI18n } from '@/i18n/provider';
import { prepareForPwaUpdate } from '@/lib/pwa/update-coordination';
import { useReleaseFeed } from '../application/release-feed-context';
import { compareStableVersions, updateStatus } from '../model/release-notes';
import { confirmUpdate } from '../application/confirm-update';
import { useUpdateOperations } from '../application/use-update-operations';
import { canInstall, installationFailed, installationPhases, preparationPhases } from '../model/installation';

const phaseLabels: Record<string, string> = {
  downloading: '正在下载更新包', verifying: '正在校验更新包', extracting: '正在解压更新包',
  ready: '更新包已准备好，等待安装', requested: '安装请求已接受', checking: '正在检查安装条件', stopping: '正在等待业务停止',
  backup: '正在备份数据库', copying: '正在更新程序文件', starting: '正在迁移数据库并启动服务', failed: '更新操作失败', success: '正在核对实际运行版本'
};
const reasonLabels: Record<string, string> = {
  PLAN_CHANGED: '准备包已变化或失效，请重新查看并确认。',
  DEPENDENCY_OPERATION_FAILED: '依赖安装失败，服务保持停止，请联系管理员检查日志。',
  DEPENDENCY_OWNERSHIP_CONFLICT: '依赖文件归属冲突，已拒绝安装。',
  LOCAL_DEPENDENCIES_INVALID: '本机受管理依赖损坏、缺失或存在未知文件，已停止准备。',
  LOCAL_RECORDS_DRIFT: '本机依赖安装记录已变化，已停止准备。',
  INSTALLATION_NOT_SUPPORTED: '更新已准备，当前版本尚不支持安装此协议。',
  INVALID_DEPENDENCY_ARTIFACT: '依赖制品或文件归属无效，未修改运行环境。',
  DOWNLOAD_FAILED: '下载失败，请检查网络后手动重试。', DOWNLOAD_TIMEOUT: '下载超时，请检查网络后手动重试。',
  DIGEST_MISMATCH: '更新包摘要不匹配，未修改当前程序。', INSUFFICIENT_SPACE: '存储空间不足，请释放空间后重试。',
  RUNTIME_NOT_WRITABLE: '程序目录不可写，请检查部署用户和目录权限。',
  UNSAFE_ARCHIVE: '更新包包含不安全的路径，已拒绝。',
  UNSUPPORTED_DEPLOYMENT: '当前部署不支持应用内更新。', PACKAGE_UNAVAILABLE: '此版本未提供应用更新包。',
  INCOMPATIBLE_ENVIRONMENT: '此更新包与固定运行环境不兼容，需要部署兼容的运行环境。', NOT_NEWER: '没有更新的可安装版本。',
  PACKAGE_NOT_READY: '准备包已变化或失效，请重新查看并确认。', UPDATE_BUSY: '已有更新操作正在进行，请查看当前状态。'
};

export function UpdateOperations() {
  const session = useAppSession();
  const admin = session?.authorization?.canManageSystem === true;
  const { t, formatNumber, formatPercent } = useI18n();
  const feed = useReleaseFeed();
  const confirm = useConfirm();
  const operations = useUpdateOperations(admin);
  const { state, runtime, check, success } = operations;
  const [confirming, setConfirming] = useState(false);
  const confirmingRef = useRef(false);
  useEffect(() => {
    if (!success || !state?.target) return;
    const identity = state.target.sha256;
    // One refresh per installed package; only UI resources use the existing PWA updater.
    if (sessionStorage.getItem('shuku:installed-refresh') === identity) return;
    let active = true;
    void prepareForPwaUpdate().then(() => {
      if (!active) return;
      sessionStorage.setItem('shuku:installed-refresh', identity);
      window.dispatchEvent(new Event('shuku:application-installed'));
    });
    return () => { active = false; };
  }, [success, state?.target]);

  const phase = state?.phase ?? 'idle';
  const installing = installationPhases.has(phase) || (!!state && installationFailed(state));
  const busy = operations.installRequested || operations.submitting || operations.observing || confirming || installing || preparationPhases.has(phase);
  const latest = check?.releases[0];
  const ready = phase === 'ready' && state?.target;
  const preparationOnly = state?.target?.format !== runtime?.install_protocol;
  const installReady = canInstall(state, runtime?.install_protocol);
  const allowed = admin && runtime?.supported === true;
  const releaseStatus = runtime && feed.state.status === 'ready' ? updateStatus(runtime.current_version, feed.state.feed) : null;
  const newVersion = latest ? (runtime && compareStableVersions(latest.version, runtime.current_version) > 0 ? latest.version : null)
    : releaseStatus?.kind === 'update-available' ? releaseStatus.latest.version : null;
  const active = phase !== 'idle' && !success;
  const failed = !!operations.error || !!state?.error || phase === 'failed';
  const feedError = feed.state.status === 'error' ? feed.state.message : null;
  const checking = !runtime || (!releaseStatus && !check) || (allowed && !state);
  const tone = failed || (!active && feedError && !check) ? 'error'
    : active || newVersion ? 'update' : checking ? 'neutral' : 'current';
  const colors = {
    error: 'border-[#E8C8C1] bg-[#FFF4F1] text-[#8D3828]',
    update: 'border-orange-200 bg-orange-50 text-orange-900',
    neutral: 'border-[#DEDAD4] bg-[#F7F5F2] text-[#716B64]',
    current: 'border-[#CFE0CF] bg-[#F2F8F1] text-[#426443]'
  };
  const Icon = tone === 'error' ? AlertCircle : tone === 'update' ? Sparkles : tone === 'neutral' ? RefreshCw : CheckCircle2;
  const message = active
    ? t(ready && !installReady ? (preparationOnly ? '更新已准备，当前版本尚不支持安装此协议。' : '准备包已变化或失效，请重新查看并确认。') : phaseLabels[phase])
    : failed ? t('更新操作失败')
    : newVersion ? t('检查到新版本 v{version}', { version: newVersion })
    : success && runtime ? t('更新成功，实际运行版本 v{version}。', { version: runtime.current_version })
    : feedError && !check ? t(feedError)
    : checking ? t('正在检查更新…')
    : releaseStatus?.kind === 'development' ? t('当前运行的是高于最新正式版的开发版本。')
    : t('当前已是最新正式版本。');
  const totalBytes = state?.summary?.total_bytes ?? state?.target?.size ?? 0;
  const progress = totalBytes > 0 ? Math.min(1, (state?.downloaded ?? 0) / totalBytes) : null;
  function refresh() {
    feed.retry();
    if (admin) operations.refresh();
  }
  async function act(install: boolean) {
    if (!allowed || !runtime || confirmingRef.current || busy || (install && !installReady)) return;
    const target = install ? state?.target && { ...state.target, plan_sha256: state.summary?.plan_sha256 } : latest && { version: latest.version, sha256: '' };
    if (!target) return;
    confirmingRef.current = true;
    setConfirming(true);
    try {
      if (!install) {
        await operations.submit('prepare', target);
      } else {
        await confirmUpdate('install', target, () => confirm({
          title: t('立即更新'),
          description: t('当前版本 v{current}，待安装版本 v{target}。更新将重启应用服务，暂停队列领取，并等待正在运行的任务结束。期间服务将暂时不可用，请勿关闭容器或设备。是否确认更新？', { current: runtime.current_version, target: target.version }),
          confirmLabel: t('确认更新'), tone: 'danger'
        }), operations.submit);
      }
    } finally { confirmingRef.current = false; setConfirming(false); }
  }
  return <div className={`mt-4 space-y-3 rounded-2xl border p-5 text-sm ${colors[tone]}`} data-testid="update-status" aria-live="polite">
    <div className="flex flex-wrap items-center gap-3">
      <Icon size={20} className="shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1 basis-48">
        <p className="font-medium">{message}</p>
        {active && state?.target ? <p className="mt-1">{t('本次更新包：v{version}', { version: state.target.version })}</p> : null}
        {phase === 'downloading' && progress !== null ? <p className="mt-1">{formatPercent(progress)}</p> : null}
      </div>
      {allowed && installReady ? <button type="button" disabled={busy} onClick={() => void act(true)} className="min-h-10 rounded-xl bg-[#ED4D2D] px-4 text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-400 disabled:opacity-50">{t('立即更新')}</button>
        : allowed && (!ready || (!preparationOnly && !installReady)) && latest?.installable && newVersion && !installing ? <button type="button" disabled={busy} onClick={() => void act(false)} className="min-h-10 rounded-xl bg-[#ED4D2D] px-4 text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-400 disabled:opacity-50">{t('下载更新')}</button> : null}
      {!busy ? <button type="button" onClick={refresh} className="inline-flex min-h-10 items-center gap-2 rounded-xl px-2 underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-400"><RefreshCw size={16} aria-hidden="true" />{t('刷新更新状态')}</button> : null}
    </div>
    {operations.observing && !preparationPhases.has(phase) ? <p>{t('正在确认更新状态，安装期间服务可能暂时不可用。')}</p> : null}
    {operations.error ? <p role="alert">{t(reasonLabels[operations.error] ?? operations.error)}</p> : null}
    {state?.error ? <p role="alert">{t('操作失败：{reason}', { reason: t(reasonLabels[state.error] ?? '请根据错误码检查日志：{code}', { code: state.error }) })}</p> : null}
    {feedError && (active || check) ? <p role="alert">{t(feedError)}</p> : null}
    {runtime && !runtime.supported ? <p>{t('当前部署不支持应用内更新。')}</p>
      : runtime && !admin ? <p>{t('仅系统管理员可下载或安装更新。')}</p>
      : !ready && newVersion && latest && !latest.installable ? <p>{t(reasonLabels[latest.reason ?? ''] ?? '此版本未提供应用更新包。')}</p> : null}
    {runtime ? <details className="text-xs">
      <summary className="w-fit cursor-pointer rounded py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-400">{t('更新详情')}</summary>
      <div className="mt-2 space-y-2">
        <p>{t('实际运行版本：v{version}', { version: runtime.current_version })}</p>
        {latest ? <p>{t('远程最新版本：v{version}', { version: latest.version })}</p> : null}
        {state?.summary ? <p>{t('已下载 {downloaded} 字节，总计 {total} 字节；依赖下载 {dependencies} 字节。', { downloaded: formatNumber(state.downloaded ?? 0), total: formatNumber(state.summary.total_bytes), dependencies: formatNumber(state.summary.dependency_bytes) })}<br />{t('依赖：安装／替换 {install}，删除 {remove}，保留 {keep}。', { install: formatNumber(state.summary.install), remove: formatNumber(state.summary.remove), keep: formatNumber(state.summary.keep) })}</p> : null}
        {installing || phase === 'failed' ? <p>{t('请查看容器日志和 STORAGE_ROOT/update-tmp/installation.log。安装失败请联系管理员检查，勿删除失败标记或清空数据库。')}</p> : null}
      </div>
    </details> : null}
  </div>;
}

'use client';

import { useEffect, useRef, useState } from 'react';
import { useAppSession } from '@/components/layout/app-session-context';
import { useConfirm } from '@/components/ui/feedback';
import { useI18n } from '@/i18n/provider';
import { prepareForPwaUpdate } from '@/lib/pwa/update-coordination';
import { confirmUpdate } from '../application/confirm-update';
import { useUpdateOperations } from '../application/use-update-operations';
import { installationFailed, installationPhases, preparationPhases } from '../model/installation';

const phaseLabels: Record<string, string> = {
  idle: '尚未准备更新包', downloading: '正在下载更新包', verifying: '正在校验更新包', extracting: '正在解压更新包',
  ready: '更新包已准备好，等待安装', requested: '安装请求已接受', checking: '正在检查安装条件', stopping: '正在等待业务停止',
  backup: '正在备份数据库', copying: '正在更新程序文件', starting: '正在迁移数据库并启动服务', failed: '更新操作失败', success: '正在核对实际运行版本'
};
const reasonLabels: Record<string, string> = {
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
  const { t } = useI18n();
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

  if (!runtime) return <p className="mt-4 text-sm" role="status">{t('正在读取实际运行版本…')}</p>;
  if (!runtime.supported) return <p className="mt-4 text-sm">{t('当前部署不支持应用内更新。')}</p>;
  if (!admin) return <p className="mt-4 text-sm">{t('仅系统管理员可下载或安装更新。')}</p>;
  const phase = state?.phase ?? 'idle';
  const installing = installationPhases.has(phase) || (!!state && installationFailed(state));
  const busy = operations.installRequested || operations.submitting || operations.observing || confirming || installing || preparationPhases.has(phase);
  const latest = check?.releases[0];
  const ready = phase === 'ready' && state?.target;
  const preparationOnly = state?.target?.format === 2;
  async function act(install: boolean) {
    if (confirmingRef.current || busy || (install && preparationOnly)) return;
    const target = install ? state?.target : latest && { version: latest.version, sha256: '' };
    if (!target) return;
    confirmingRef.current = true;
    setConfirming(true);
    try {
      await confirmUpdate(install ? 'install' : 'prepare', target, () => confirm({
        title: t(install ? '安装并重启' : '下载更新'),
        description: install
          ? t('当前版本 v{current}，待安装版本 v{target}。安装期间服务将暂时不可用。系统将停止业务、更新程序并执行数据库迁移。请勿关闭容器或设备。', { current: runtime!.current_version, target: target.version })
          : t('下载 v{version}：此操作只下载并准备更新包，不会停止服务。下载完成后需要另行确认安装。', { version: target.version }),
        confirmLabel: t(install ? '确认安装' : '确认下载'), tone: install ? 'danger' : 'default'
      }), operations.submit);
    } finally { confirmingRef.current = false; setConfirming(false); }
  }
  return <div className="mt-4 space-y-3 rounded-2xl border border-[#DEDAD4] bg-[#F7F5F2] p-5 text-sm" aria-live="polite">
    <p>{t(success ? '更新成功，实际运行版本 v{version}。' : (ready && preparationOnly ? '更新已准备，当前版本尚不支持安装此协议。' : phaseLabels[phase]), { version: runtime.current_version })}</p>
    {state?.target ? <p>{t('本次更新包：v{version}', { version: state.target.version })}</p> : null}
    {latest ? <p>{t('远程最新版本：v{version}', { version: latest.version })}</p> : null}
    {phase === 'downloading' && state?.target && (state.downloaded ?? 0) > 0 ? <p>{Math.min(100, Math.floor((state.downloaded ?? 0) / (state.summary?.total_bytes ?? state.target.size) * 100))}%</p> : null}
    {operations.observing && !preparationPhases.has(phase) ? <p>{t('正在确认更新状态，安装期间服务可能暂时不可用。')}</p> : null}
    {operations.error ? <p role="alert">{t(reasonLabels[operations.error] ?? operations.error)}</p> : null}
    {state?.error ? <p role="alert">{t('操作失败：{reason}', { reason: t(reasonLabels[state.error] ?? '请根据错误码检查日志：{code}', { code: state.error }) })}</p> : null}
    {installing || state?.phase === 'failed' ? <p>{t('请查看容器日志和 STORAGE_ROOT/update-tmp/installation.log。安装失败请联系管理员检查，勿删除失败标记或清空数据库。')}</p> : null}
    {!ready && latest && !latest.installable ? <p>{t(reasonLabels[latest.reason ?? ''] ?? '此版本未提供应用更新包。')}</p> : null}
    {ready && !preparationOnly ? <button type="button" disabled={busy} onClick={() => void act(true)} className="min-h-10 rounded-xl bg-[#ED4D2D] px-4 text-white disabled:opacity-50">{t('安装并重启')}</button>
      : !ready && latest?.installable && !installing ? <button type="button" disabled={busy} onClick={() => void act(false)} className="min-h-10 rounded-xl bg-[#ED4D2D] px-4 text-white disabled:opacity-50">{t('下载更新')}</button> : null}
    {!operations.observing && !operations.submitting ? <button type="button" onClick={operations.refresh} className="ml-3 min-h-10 underline">{t('刷新更新状态')}</button> : null}
  </div>;
}

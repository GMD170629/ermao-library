'use client';

import {
  comparePublicationLocations,
  publicationNavigationHref,
  type ReaderLocation,
  type ReaderPreferences
} from '@shuku/reader-core';
import { AlertTriangle, LoaderCircle, RotateCcw } from 'lucide-react';
import Image from 'next/image';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import {
  activateReaderUser,
  currentReaderServerIdentity,
  emitReaderDebug,
  getReaderRuntime,
  publicationLocationFromDomain,
  syncStateKey,
  v4LocationToDomain,
  type ExactProgressRecord,
  type PendingProgressMutation,
  type ReaderProgressSnapshot,
  type RemoteProgressNotice
} from '../../../lib/reader';
import {
  READER_DEVICE_PREFERENCES_KEY,
  clearDeviceReaderPreferences,
  readDeviceReaderPreferences,
  writeDeviceReaderPreferences
} from '../../../lib/reader-device-preferences';
import { withBasePath } from '../../../lib/base-path';
import { BEFORE_PWA_UPDATE_EVENT, type BeforePwaUpdateDetail } from '../../../lib/pwa/update-coordination';
import { DEFAULT_READER_THEME, readerThemeSurfaces, resolveReaderTheme } from '../reader-theme';
import { fetchReaderBootstrap, ReaderBootstrapError, type ReaderBootstrap } from './api';
import { requestedPdfPage } from './direct-page-target';
import { resolveRequestedPublicationHref } from './publication-direct-target';
import { decidePendingVsServer, resolveStartupResume } from './local-resume';
import { ReaderEngineRuntime } from './reader-engine-runtime';
import { useReaderPwaSurface } from './use-reader-pwa-surface';
import { I18nText, type I18nContextValue } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

const openingStorageKey = 'shuku:reader:opening';

function requireReflowableSourceFormat(bootstrap: ReaderBootstrap) {
  if (bootstrap.readerType !== 'reflowable' || !bootstrap.sourceFormat) {
    throw new Error('小说阅读器启动信息缺少源格式');
  }
  if (bootstrap.source.kind !== 'reflowable') throw new Error('REFLOWABLE_SOURCE_FORMAT_MISSING');
  return bootstrap.source.sourceFormat;
}

type OpeningContext = {
  volumeId: string;
  title: string;
  author?: string;
  coverUrl?: string;
  gradient?: string;
  rect?: { left: number; top: number; width: number; height: number } | null;
};

type PageState = {
  requestId: number;
  status: 'loading' | 'ready' | 'error';
  bootstrap: ReaderBootstrap | null;
  preferences: ReaderPreferences | null;
  error: string;
};

type PageAction =
  | { type: 'load'; requestId: number }
  | { type: 'ready'; requestId: number; bootstrap: ReaderBootstrap; preferences: ReaderPreferences }
  | { type: 'error'; requestId: number; error: string }
  | { type: 'preferences'; preferences: ReaderPreferences };

const initialPageState: PageState = { requestId: 0, status: 'loading', bootstrap: null, preferences: null, error: '' };

type StartupConflictState = {
  bootstrap: ReaderBootstrap;
  preferences: ReaderPreferences;
  localExact: ExactProgressRecord;
  pending: PendingProgressMutation;
  server: ReaderProgressSnapshot;
};

function pageReducer(state: PageState, action: PageAction): PageState {
  if (action.type !== 'load' && 'requestId' in action && action.requestId !== state.requestId) return state;
  if (action.type === 'load') return { requestId: action.requestId, status: 'loading', bootstrap: null, preferences: null, error: '' };
  if (action.type === 'ready') return { ...state, status: 'ready', bootstrap: action.bootstrap, preferences: action.preferences, error: '' };
  if (action.type === 'error') return { ...state, status: 'error', error: action.error };
  return { ...state, preferences: action.preferences };
}

function readOpeningContext(volumeId: string): OpeningContext | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(openingStorageKey);
    if (!raw) return null;
    window.sessionStorage.removeItem(openingStorageKey);
    const value = JSON.parse(raw) as OpeningContext;
    return value.volumeId === volumeId ? value : null;
  } catch {
    return null;
  }
}

function formatDownloadedBytes(value: number, formatNumber: (input: number, options?: Intl.NumberFormatOptions) => string) {
  if (value < 1024) return `${formatNumber(value)} B`;
  if (value < 1024 * 1024) return `${formatNumber(value / 1024, { maximumFractionDigits: 1 })} KB`;
  return `${formatNumber(value / (1024 * 1024), { maximumFractionDigits: 1 })} MB`;
}

function remoteProgressLabel(
  bootstrap: ReaderBootstrap,
  notice: RemoteProgressNotice,
  formatNumber: (input: number, options?: Intl.NumberFormatOptions) => string,
  translate: I18nContextValue['t']
) {
  const locator = notice.locator;
  if (locator.kind === 'pdf' || locator.kind === 'comic') {
    return translate('第 {value0} 页', { value0: formatNumber(locator.pageIndex + 1) });
  }
  if (locator.kind === 'audio') {
    const seconds = Math.floor(locator.positionMillis / 1_000);
    return `${formatNumber(Math.floor(seconds / 60))}:${formatNumber(seconds % 60, { minimumIntegerDigits: 2 })}`;
  }
  const href = locator.engineLocator.payload.href;
  const chapter = bootstrap.units.find((unit) => unit.href === href);
  return chapter?.title ?? `${formatNumber(notice.displayPercent, { maximumFractionDigits: 1 })}%`;
}

function OpeningCover({ context, ready, background, color, indexProgress, downloadProgress, onCancel }: {
  context: OpeningContext | null;
  ready: boolean;
  background: string;
  color: string;
  indexProgress: { completed: number; total: number; percent: number } | null;
  downloadProgress: { loadedBytes: number; totalBytes: number | null; percent: number | null } | null;
  onCancel: () => void;
}) {
  const { t: i18nAttribute, formatNumber } = useAttributeI18n();
  const [visible, setVisible] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const reducedMotion = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  useEffect(() => {
    if (reducedMotion) {
      setExpanded(true);
      return undefined;
    }
    const frame = window.requestAnimationFrame(() => setExpanded(true));
    return () => window.cancelAnimationFrame(frame);
  }, [reducedMotion]);

  useEffect(() => {
    if (!ready) return undefined;
    const timer = window.setTimeout(() => setVisible(false), reducedMotion ? 0 : context ? 360 : 120);
    return () => window.clearTimeout(timer);
  }, [context, ready, reducedMotion]);

  if (!visible) return null;
  const initial = context?.rect;
  const targetWidth = Math.min(220, Math.round((typeof window === 'undefined' ? 390 : window.innerWidth) * 0.42));
  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center overflow-hidden transition-opacity duration-300 motion-reduce:transition-none"
      style={{
        backgroundColor: background,
        color,
        opacity: ready ? 0 : 1,
        pointerEvents: ready ? 'none' : 'auto'
      }}
      data-reader-opening-cover={ready ? 'ready' : 'loading'}
      aria-hidden={ready}
    >
      {context?.coverUrl ? (
        <Image
          src={withBasePath(context.coverUrl)}
          alt=""
          width={targetWidth}
          height={Math.round(targetWidth * 1.42)}
          unoptimized
          className="absolute rounded-lg object-cover shadow-2xl transition-all duration-500 ease-out motion-reduce:transition-none"
          style={expanded || !initial ? {
            left: `calc(50% - ${targetWidth / 2}px)`,
            top: 'calc(50% - 10rem)',
            width: targetWidth,
            height: Math.round(targetWidth * 1.42)
          } : initial}
        />
      ) : <LoaderCircle size={30} className="animate-spin motion-reduce:animate-none" />}
      <div className="absolute inset-x-6 bottom-[calc(4rem+var(--shuku-safe-area-bottom))] text-center">
        <div className="line-clamp-2 text-lg font-semibold">{context?.title ?? i18nAttribute("正在打开阅读器")}</div>
        {context?.author ? <div className="mt-1 text-sm opacity-65">{context.author}</div> : null}
        {downloadProgress ? (
          <div className="mx-auto mt-5 w-full max-w-sm">
            <div className="text-sm font-medium"><I18nText>首次下载书籍</I18nText></div>
            <div
              className="mt-3 h-2 overflow-hidden rounded-full bg-current/15"
              role="progressbar"
              aria-label={i18nAttribute('书籍下载进度')}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={downloadProgress.percent === null ? undefined : Math.round(downloadProgress.percent)}
            >
              <div
                className={`h-full rounded-full bg-current ${downloadProgress.percent === null ? 'w-1/3 animate-pulse motion-reduce:animate-none' : 'transition-[width] duration-150'}`}
                style={downloadProgress.percent === null ? undefined : { width: `${downloadProgress.percent}%` }}
              />
            </div>
            <div className="mt-2 text-xs tabular-nums opacity-65">
              {downloadProgress.totalBytes
                ? i18nAttribute('已下载 {value0} / {value1} · {value2}%', {
                  value0: formatDownloadedBytes(downloadProgress.loadedBytes, formatNumber),
                  value1: formatDownloadedBytes(downloadProgress.totalBytes, formatNumber),
                  value2: Math.round(downloadProgress.percent ?? 0)
                })
                : i18nAttribute('已下载 {value0}', { value0: formatDownloadedBytes(downloadProgress.loadedBytes, formatNumber) })}
            </div>
            <div className="mt-1 text-xs opacity-55"><I18nText>首次打开需要下载一次，之后将直接进入阅读。</I18nText></div>
            <button type="button" onClick={onCancel} className="mt-4 min-h-11 rounded-xl bg-current/10 px-4 text-sm transition hover:bg-current/15"><I18nText>取消并返回书库</I18nText></button>
          </div>
        ) : indexProgress ? (
          <div className="mx-auto mt-5 w-full max-w-sm">
            <div className="text-sm font-medium"><I18nText>正在建立全书位置索引</I18nText></div>
            <div
              className="mt-3 h-2 overflow-hidden rounded-full bg-current/15"
              role="progressbar"
              aria-label={i18nAttribute("全书位置索引进度")}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(indexProgress.percent)}
            >
              <div
                className="h-full rounded-full bg-current transition-[width] duration-150"
                style={{ width: `${indexProgress.percent}%` }}
              />
            </div>
            <div className="mt-2 text-xs tabular-nums opacity-65">
              {indexProgress.total > 0
                ? i18nAttribute("已处理 {value0} / {value1} 章 · {value2}%", { value0: indexProgress.completed, value1: indexProgress.total, value2: Math.round(indexProgress.percent) })
                : i18nAttribute("正在准备章节索引…")}
            </div>
            <div className="mt-1 text-xs opacity-55"><I18nText>首次打开需要完成一次，之后将直接进入阅读。</I18nText></div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function ReaderV4Page({ volumeId }: { volumeId: string }) {
  const { t: translate, formatDateTime, formatNumber } = useAttributeI18n();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedHref = searchParams.get('href');
  const requestedPage = searchParams.get('page');
  const [state, dispatch] = useReducer(pageReducer, initialPageState);
  const [retry, setRetry] = useState(0);
  const [readerReady, setReaderReady] = useState(false);
  const [indexProgress, setIndexProgress] = useState<{ completed: number; total: number; percent: number } | null>(null);
  const [downloadProgress, setDownloadProgress] = useState<{ loadedBytes: number; totalBytes: number | null; percent: number | null } | null>(null);
  const [storageError, setStorageError] = useState('');
  const [startupConflict, setStartupConflict] = useState<StartupConflictState | null>(null);
  const [remoteNotice, setRemoteNotice] = useState<RemoteProgressNotice | null>(null);
  const [externalNavigation, setExternalNavigation] = useState<{ id: number; location: ReaderLocation } | null>(null);
  const [systemDark, setSystemDark] = useState(false);
  const [openingContext] = useState<OpeningContext | null>(() => readOpeningContext(volumeId));
  const requestSequenceRef = useRef(0);
  const pendingLocationWriteRef = useRef<Promise<unknown>>(Promise.resolve());
  const currentExactRef = useRef<import('@shuku/reader-core').PublicationLocation | null>(null);
  const startupCloudRef = useRef<{ pendingKey: string; snapshot: ReaderProgressSnapshot } | null>(null);
  const remoteJumpRef = useRef<ReaderProgressSnapshot | null>(null);
  const acceptedRemoteExactRef = useRef<import('@shuku/reader-core').PublicationLocation | null>(null);
  const runtime = getReaderRuntime();
  const effectivePreferences = useMemo(() => state.preferences
    ? {
        ...state.preferences,
        appearance: {
          ...state.preferences.appearance,
          theme: resolveReaderTheme(
            state.preferences.appearance.theme,
            state.preferences.appearance.themeMode,
            systemDark
          )
        }
      }
    : null, [state.preferences, systemDark]);
  const activeTheme = state.status === 'error'
    ? 'night'
    : effectivePreferences?.appearance.theme ?? DEFAULT_READER_THEME;
  const activeSurface = readerThemeSurfaces[activeTheme];
  useReaderPwaSurface(activeTheme);

  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    const update = () => setSystemDark(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);

  const readerHref = useCallback((nextVolumeId: string, pageIndex?: number) => {
    const query = new URLSearchParams();
    if (pageIndex && pageIndex > 0) query.set('page', String(pageIndex));
    return `/reader/${nextVolumeId}${query.size ? `?${query}` : ''}`;
  }, []);

  useEffect(() => {
    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;
    const controller = new AbortController();
    setReaderReady(false);
    setIndexProgress(null);
    setDownloadProgress(null);
    setStorageError('');
    setStartupConflict(null);
    setRemoteNotice(null);
    dispatch({ type: 'load', requestId });

    void (async () => {
      let bootstrap = await fetchReaderBootstrap(volumeId, controller.signal);
      if (controller.signal.aborted) return;
      let hasDirectTarget = false;
      if (bootstrap.readerType === 'reflowable' && requestedHref) {
        const sourceFormat = requireReflowableSourceFormat(bootstrap);
        const targetHref = resolveRequestedPublicationHref(bootstrap.units, requestedHref);
        const navigationHref = publicationNavigationHref(sourceFormat, targetHref);
        if (navigationHref) {
          bootstrap = {
            ...bootstrap,
            initialLocation: { kind: 'reflowable', format: sourceFormat, href: navigationHref }
          };
          hasDirectTarget = true;
        } else {
          emitReaderDebug('warning', '已忽略不属于当前 Publication 的章节直达目标', { requestedHref });
        }
      } else if (bootstrap.readerType === 'comic' && requestedPage) {
        const pageIndex = Number(requestedPage);
        const pageExists = Number.isInteger(pageIndex) && bootstrap.pages.some((page) => page.pageIndex === pageIndex);
        if (pageExists) {
          const pageOrder = bootstrap.pages.findIndex((page) => page.pageIndex === pageIndex);
          const progression = bootstrap.pages.length > 1 ? pageOrder / (bootstrap.pages.length - 1) : 0;
          bootstrap = {
            ...bootstrap,
            initialLocation: { kind: 'comic', volumeId: bootstrap.volume.id, pageIndex },
            progressPercent: Math.round(progression * 100)
          };
          hasDirectTarget = true;
        } else {
          emitReaderDebug('warning', '已忽略不属于当前漫画卷册的书签页码', { requestedPage });
        }
      } else if (bootstrap.readerType === 'pdf' && requestedPage) {
        const pageNumber = requestedPdfPage(requestedPage, bootstrap.volume.pageCount);
        if (pageNumber !== null) {
          bootstrap = {
            ...bootstrap,
            initialLocation: { kind: 'pdf', pageIndex: pageNumber - 1, pageProgression: 0 }
          };
          hasDirectTarget = true;
        } else {
          emitReaderDebug('warning', '已忽略超出当前 PDF 范围的页码', { requestedPage });
        }
      }
      const clientId = await runtime.storage.getClientId();
      const localExact = await runtime.storage.getExactProgress({
        serverIdentity: currentReaderServerIdentity(),
        userId: bootstrap.userId,
        clientId,
        workId: bootstrap.version.workId,
        volumeId: bootstrap.volume.id
      }).catch(() => null);
      const pending = await runtime.storage.getPendingProgressForIdentity({
        serverIdentity: currentReaderServerIdentity(),
        userId: bootstrap.userId,
        clientId,
        workId: bootstrap.version.workId,
        volumeId: bootstrap.volume.id
      }).catch(() => null);
      const pendingDecision = decidePendingVsServer({
        localExact,
        pending,
        serverSnapshot: bootstrap.serverProgressSnapshot
      });
      if (pendingDecision.kind === 'server' && pendingDecision.discardPending && pending) {
        await runtime.storage.deletePendingProgress(pending.key, pending.mutationId);
      }
      const startupResume = resolveStartupResume({
        localExact,
        serverSnapshot: bootstrap.serverProgressSnapshot,
        context: bootstrap.readerType === 'reflowable' ? {
          readerKind: 'reflowable',
          sourceFormat: requireReflowableSourceFormat(bootstrap)
        } : {
          readerKind: bootstrap.readerType
        },
        serverLocation: bootstrap.initialLocation,
        serverPercent: bootstrap.progressPercent,
        hasDirectTarget
      });
      const pendingResume = pendingDecision.kind === 'local-pending' ? pendingDecision.localExact : null;
      if (pendingResume && !hasDirectTarget) {
        const localLocation = v4LocationToDomain(
          pendingResume.locator,
          bootstrap.volume.id,
          bootstrap.readerType === 'reflowable' ? requireReflowableSourceFormat(bootstrap) : null
        );
        bootstrap = {
          ...bootstrap,
          initialLocation: localLocation,
          progressPercent: pendingResume.displayPercent ?? bootstrap.progressPercent
        };
        emitReaderDebug('info', '启动时恢复尚未上传的本机精确阅读位置', {
          volumeId: bootstrap.volume.id,
          capturedAtEpochMillis: pendingResume.capturedAtEpochMillis
        });
      }
      const preferences = readDeviceReaderPreferences(
        bootstrap.userId,
        bootstrap.serverPreferences.settings
      );
      if (controller.signal.aborted) return;
      if (pendingDecision.kind === 'requires-choice') {
        setStartupConflict({
          bootstrap,
          preferences,
          localExact: pendingDecision.localExact,
          pending: pendingDecision.pending,
          server: pendingDecision.server
        });
        return;
      }
      activateReaderUser(bootstrap.userId);
      emitReaderDebug('info', 'Reader v4 启动完成', {
        volumeId: bootstrap.volume.id,
        workId: bootstrap.version.workId,
        preferences: 'device-default'
      });
      dispatch({ type: 'ready', requestId, bootstrap, preferences });
    })().catch((reason) => {
      if (controller.signal.aborted) return;
      const bootstrapMessage = reason instanceof ReaderBootstrapError
        ? ({
            VOLUME_FORMAT_UNSUPPORTED: '当前文件格式尚未开放阅读支持',
            READER_FORMAT_MORPHOLOGY_MISMATCH: '文件格式与阅读器类型不匹配',
            PUBLICATION_PROCESSING: '内容仍在准备中，请稍后重试',
            PUBLICATION_CORRUPT: '文件已损坏，无法打开',
            PUBLICATION_DRM: '受 DRM 保护的文件无法打开',
            PUBLICATION_FAILED: '内容准备失败，请重新导入'
          } as const)[reason.code]
        : undefined;
      dispatch({ type: 'error', requestId, error: bootstrapMessage ? translate(bootstrapMessage) : reason instanceof Error ? reason.message : translate('读取阅读器启动信息失败') });
    });

    return () => controller.abort();
  }, [requestedHref, requestedPage, retry, runtime.storage, translate, volumeId]);

  const chooseStartupLocal = useCallback(async () => {
    const conflict = startupConflict;
    if (!conflict) return;
    const sourceFormat = conflict.bootstrap.readerType === 'reflowable'
      ? requireReflowableSourceFormat(conflict.bootstrap) : null;
    const location = v4LocationToDomain(
      conflict.localExact.locator,
      conflict.bootstrap.volume.id,
      sourceFormat
    );
    await runtime.progress.continueStartupWithLocal(conflict.pending, conflict.server.revision);
    activateReaderUser(conflict.bootstrap.userId);
    setStartupConflict(null);
    dispatch({
      type: 'ready',
      requestId: state.requestId,
      bootstrap: {
        ...conflict.bootstrap,
        initialLocation: location,
        progressPercent: conflict.localExact.displayPercent ?? conflict.bootstrap.progressPercent
      },
      preferences: conflict.preferences
    });
  }, [runtime.progress, startupConflict, state.requestId]);

  const chooseStartupCloud = useCallback(async () => {
    const conflict = startupConflict;
    if (!conflict) return;
    await runtime.storage.deletePendingProgress(conflict.pending.key, conflict.pending.mutationId);
    startupCloudRef.current = { pendingKey: conflict.pending.key, snapshot: conflict.server };
    activateReaderUser(conflict.bootstrap.userId);
    setStartupConflict(null);
    dispatch({
      type: 'ready',
      requestId: state.requestId,
      bootstrap: conflict.bootstrap,
      preferences: conflict.preferences
    });
  }, [runtime.storage, startupConflict, state.requestId]);

  const cancelStartupConflict = useCallback(() => {
    const conflict = startupConflict;
    if (!conflict) return;
    router.push(`/works/${conflict.bootstrap.version.workId}?volumeId=${encodeURIComponent(conflict.bootstrap.volume.id)}`);
  }, [router, startupConflict]);

  const savePreferences = useCallback((preferences: ReaderPreferences) => {
    const bootstrap = state.bootstrap;
    if (!bootstrap) return;
    dispatch({ type: 'preferences', preferences });
    setStorageError('');
    try {
      writeDeviceReaderPreferences(bootstrap.userId, preferences);
    } catch (reason) {
      setStorageError(reason instanceof Error ? reason.message : '本机阅读设置保存失败');
    }
  }, [state.bootstrap]);

  useEffect(() => runtime.progress.subscribeRemoteProgress((changedVolumeId, notice) => {
    if (changedVolumeId === volumeId) setRemoteNotice(notice);
  }), [runtime.progress, volumeId]);

  useEffect(() => {
    const bootstrap = state.bootstrap;
    if (!bootstrap) return undefined;
    let active = true;
    void runtime.storage.getClientId().then((clientId) => {
      if (!active) return;
      const initialExact = bootstrap.initialLocation
        ? publicationLocationFromDomain(bootstrap.initialLocation)
        : bootstrap.serverProgressSnapshot?.locator ?? null;
      currentExactRef.current = initialExact;
      runtime.progress.beginSession(
        bootstrap.volume.id,
        clientId,
        bootstrap.serverProgressSnapshot,
        initialExact
      );
    });
    return () => {
      active = false;
      runtime.progress.endSession(bootstrap.volume.id);
    };
  }, [runtime.progress, runtime.storage, state.bootstrap]);

  useEffect(() => {
    const bootstrap = state.bootstrap;
    if (!bootstrap || !readerReady) return undefined;
    const check = () => { void runtime.progress.checkRemoteProgress(bootstrap.volume.id).catch(() => undefined); };
    check();
    const onVisibility = () => { if (document.visibilityState === 'visible') check(); };
    window.addEventListener('online', check);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('online', check);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [readerReady, runtime.progress, state.bootstrap]);

  const resetPreferences = useCallback(async () => {
    const bootstrap = state.bootstrap;
    if (!bootstrap) return;
    try {
      clearDeviceReaderPreferences(bootstrap.userId);
      const preferences = readDeviceReaderPreferences(bootstrap.userId, bootstrap.serverPreferences.settings);
      dispatch({ type: 'preferences', preferences });
      setStorageError('');
    } catch (reason) {
      setStorageError(reason instanceof Error ? reason.message : '恢复阅读默认设置失败');
    }
  }, [state.bootstrap]);

  useEffect(() => {
    const bootstrap = state.bootstrap;
    if (!bootstrap) return undefined;
    const refresh = () => dispatch({
      type: 'preferences',
      preferences: readDeviceReaderPreferences(bootstrap.userId, bootstrap.serverPreferences.settings)
    });
    const handleStorage = (event: StorageEvent) => {
      if (event.key?.includes(READER_DEVICE_PREFERENCES_KEY)) refresh();
    };
    window.addEventListener('storage', handleStorage);
    window.addEventListener('shuku:reader-device-preferences-changed', refresh);
    return () => {
      window.removeEventListener('storage', handleStorage);
      window.removeEventListener('shuku:reader-device-preferences-changed', refresh);
    };
  }, [state.bootstrap]);

  const saveLocation = useCallback((location: Parameters<ReaderV4PageLocationHandler>[0], percent: number) => {
    const bootstrap = state.bootstrap;
    if (!bootstrap) return;
    const exactLocation = publicationLocationFromDomain(location);
    if (!exactLocation) {
      setStorageError(translate('当前阅读位置尚未形成可跨端验证的精确锚点'));
      return;
    }
    const previousExact = currentExactRef.current;
    currentExactRef.current = exactLocation;
    const startupCloud = startupCloudRef.current;
    if (startupCloud && comparePublicationLocations(startupCloud.snapshot.locator, exactLocation).precision === 'exact') {
      startupCloudRef.current = null;
      acceptedRemoteExactRef.current = startupCloud.snapshot.locator;
      pendingLocationWriteRef.current = runtime.progress.acceptVerifiedRemote({
        serverIdentity: currentReaderServerIdentity(),
        userId: bootstrap.userId,
        workId: bootstrap.version.workId,
        volumeId: bootstrap.volume.id,
        pendingKey: startupCloud.pendingKey,
        snapshot: startupCloud.snapshot
      });
      return;
    }
    if (remoteJumpRef.current) return;
    const acceptedRemoteExact = acceptedRemoteExactRef.current;
    if (acceptedRemoteExact) {
      if (comparePublicationLocations(acceptedRemoteExact, exactLocation).precision === 'exact') return;
      acceptedRemoteExactRef.current = null;
    }
    // Readium can emit the verified destination again after a programmatic
    // navigation callback has completed. Repeated capture of the same exact
    // block is not a genuine reading movement and must never create a second
    // mutation (in particular after accepting a remote progress notice).
    if (previousExact
      && comparePublicationLocations(previousExact, exactLocation).precision === 'exact') return;
    const write = runtime.progress.enqueue({
      serverIdentity: currentReaderServerIdentity(),
      userId: bootstrap.userId,
      workId: bootstrap.version.workId,
      volumeId: bootstrap.volume.id,
      baseRevision: runtime.progress.getLatestServerSnapshot(bootstrap.volume.id)?.revision
        ?? bootstrap.serverProgressSnapshot?.revision ?? 0,
      locator: exactLocation,
      displayPercent: percent
    }).catch((reason) => {
      setStorageError(reason instanceof Error ? reason.message : '阅读进度无法写入本机');
    });
    pendingLocationWriteRef.current = write;
  }, [runtime.progress, state.bootstrap, translate]);

  const jumpToRemoteProgress = useCallback(() => {
    const bootstrap = state.bootstrap;
    const notice = remoteNotice;
    if (!bootstrap || !notice) return;
    const sourceFormat = bootstrap.readerType === 'reflowable' ? requireReflowableSourceFormat(bootstrap) : null;
    const location = v4LocationToDomain(notice.locator, bootstrap.volume.id, sourceFormat);
    if (!location) return;
    const snapshot: ReaderProgressSnapshot = {
      schemaVersion: 4,
      clientId: notice.sourceClientId,
      revision: notice.revision,
      locator: notice.locator,
      displayPercent: notice.displayPercent,
      receivedAtEpochMillis: notice.receivedAtEpochMillis,
      ...(notice.capturedAtEpochMillis === undefined ? {} : { capturedAtEpochMillis: notice.capturedAtEpochMillis })
    };
    remoteJumpRef.current = snapshot;
    setExternalNavigation((current) => ({ id: (current?.id ?? 0) + 1, location }));
  }, [remoteNotice, state.bootstrap]);

  const handleExternalNavigationResult = useCallback((id: number, accepted: boolean) => {
    if (externalNavigation?.id !== id) return;
    const snapshot = remoteJumpRef.current;
    const bootstrap = state.bootstrap;
    setExternalNavigation(null);
    remoteJumpRef.current = null;
    if (!accepted || !snapshot || !bootstrap || !currentExactRef.current
      || comparePublicationLocations(snapshot.locator, currentExactRef.current).precision !== 'exact') {
      setStorageError(translate('无法精确恢复到另一设备的位置'));
      return;
    }
    acceptedRemoteExactRef.current = snapshot.locator;
    const clientIdPromise = runtime.storage.getClientId();
    pendingLocationWriteRef.current = clientIdPromise.then((clientId) => runtime.progress.acceptVerifiedRemote({
      serverIdentity: currentReaderServerIdentity(),
      userId: bootstrap.userId,
      workId: bootstrap.version.workId,
      volumeId: bootstrap.volume.id,
      pendingKey: syncStateKey({ serverIdentity: currentReaderServerIdentity(), userId: bootstrap.userId, clientId, workId: bootstrap.version.workId, volumeId: bootstrap.volume.id }),
      snapshot
    }));
  }, [externalNavigation, runtime.progress, runtime.storage, state.bootstrap, translate]);

  useEffect(() => {
    const handleBeforePwaUpdate = (event: Event) => {
      const detail = (event as CustomEvent<BeforePwaUpdateDetail>).detail;
      if (!detail?.waitUntil) return;
      detail.waitUntil(
        pendingLocationWriteRef.current.then(() => runtime.progress.flushNow())
      );
    };
    window.addEventListener(BEFORE_PWA_UPDATE_EVENT, handleBeforePwaUpdate);
    return () => window.removeEventListener(BEFORE_PWA_UPDATE_EVENT, handleBeforePwaUpdate);
  }, [runtime.progress]);

  if (startupConflict) {
    return (
      <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/45 p-5" role="presentation">
        <div className="w-full max-w-md rounded-2xl bg-white p-5 text-[#2D2926] shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="reader-startup-conflict-title">
          <h1 id="reader-startup-conflict-title" className="text-lg font-semibold"><I18nText>选择阅读位置</I18nText></h1>
          <p className="mt-2 text-sm leading-6 text-[#6F6963]"><I18nText>本机有尚未同步的阅读位置，同时云端进度已更新。请选择本次从哪里继续。</I18nText></p>
          <div className="mt-5 grid gap-2">
            <button type="button" className="min-h-11 rounded-xl bg-[#2D2926] px-4 text-sm font-medium text-white" onClick={() => void chooseStartupLocal()}><I18nText>继续本机位置</I18nText></button>
            <button type="button" className="min-h-11 rounded-xl border border-[#D8D1CA] px-4 text-sm font-medium" onClick={() => void chooseStartupCloud()}><I18nText>使用云端位置</I18nText></button>
            <button type="button" className="min-h-11 rounded-xl px-4 text-sm text-[#6F6963]" onClick={cancelStartupConflict}><I18nText>取消</I18nText></button>
          </div>
        </div>
      </div>
    );
  }

  if (state.status === 'error') {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950 p-6 text-center text-white">
        <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-white/5 p-6">
          <AlertTriangle className="mx-auto text-amber-300" size={30} />
          <div className="mt-4 text-lg font-semibold"><I18nText>阅读器无法启动</I18nText></div>
          <p className="mt-2 text-sm text-slate-300">{state.error}</p>
          <div className="mt-5 grid grid-cols-2 gap-2">
            <button type="button" onClick={() => router.push('/library')} className="min-h-11 rounded-xl bg-white/10 px-3 text-sm"><I18nText>返回书库</I18nText></button>
            <button type="button" onClick={() => setRetry((value) => value + 1)} className="flex min-h-11 items-center justify-center gap-2 rounded-xl bg-blue-600 px-3 text-sm"><RotateCcw size={16} /><I18nText>重试</I18nText></button>
          </div>
        </div>
      </div>
    );
  }

  const bootstrap = state.bootstrap;
  const preferences = state.preferences;
  return (
    <>
      {bootstrap && preferences && effectivePreferences ? (
        <ReaderEngineRuntime
          key={`${bootstrap.volume.id}:${retry}`}
          bootstrap={bootstrap}
          preferences={preferences}
          effectivePreferences={effectivePreferences}
          onPreferencesChange={savePreferences}
          onResetPreferences={resetPreferences}
          onLocationChange={saveLocation}
          onBack={() => router.push(`/works/${bootstrap.version.workId}?volumeId=${encodeURIComponent(bootstrap.volume.id)}`)}
          onRetry={() => setRetry((value) => value + 1)}
          onSelectVolume={(nextVolumeId, pageIndex) => router.push(readerHref(nextVolumeId, pageIndex))}
          onIndexProgress={setIndexProgress}
          onDownloadProgress={setDownloadProgress}
          onReady={() => setReaderReady(true)}
          bookCache={runtime.storage}
          pdfRangeCache={runtime.storage}
          onStorageWarning={setStorageError}
          externalNavigation={externalNavigation}
          onExternalNavigationResult={handleExternalNavigationResult}
        />
      ) : (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center"
          style={{ backgroundColor: activeSurface.background, color: activeSurface.color }}
        >
          <LoaderCircle className="animate-spin" size={30} />
        </div>
      )}
      {storageError ? (
        <div className="fixed inset-x-3 top-[calc(1rem+var(--shuku-safe-area-top))] z-[110] mx-auto max-w-md rounded-xl border border-amber-300/30 bg-amber-950/95 px-4 py-3 text-sm text-amber-100 shadow-xl" role="alert">
          {storageError}
        </div>
      ) : null}
      {remoteNotice && bootstrap ? (
        <div className="fixed inset-x-3 bottom-[calc(1rem+var(--shuku-safe-area-bottom))] z-[105] mx-auto flex max-w-xl items-center gap-3 rounded-2xl border border-black/10 bg-white/95 px-4 py-3 text-[#2D2926] shadow-xl backdrop-blur" aria-live="polite">
          <button type="button" className="min-w-0 flex-1 text-left" onClick={jumpToRemoteProgress}>
            <span className="block text-sm font-medium">
              {translate('其他设备已阅读至 {value0}', { value0: remoteProgressLabel(bootstrap, remoteNotice, formatNumber, translate) })}
            </span>
            <span className="mt-0.5 block text-xs text-[#746E68]">
              {formatDateTime(remoteNotice.capturedAtEpochMillis ?? remoteNotice.receivedAtEpochMillis)}
            </span>
          </button>
          <button type="button" className="min-h-10 shrink-0 rounded-lg px-3 text-sm font-medium" onClick={jumpToRemoteProgress}><I18nText>跳转</I18nText></button>
          <button type="button" className="grid size-10 shrink-0 place-items-center rounded-lg text-[#746E68]" aria-label={translate('关闭其他设备阅读进度提示')} onClick={() => runtime.progress.dismissRemoteProgress(bootstrap.volume.id)}>
            <span aria-hidden="true">×</span>
          </button>
        </div>
      ) : null}
      <OpeningCover
        context={openingContext}
        ready={readerReady}
        background={activeSurface.background}
        color={activeSurface.color}
        indexProgress={indexProgress}
        downloadProgress={downloadProgress}
        onCancel={() => router.push('/library')}
      />
    </>
  );
}

type ReaderV4PageLocationHandler = (location: import('@shuku/reader-core').ReaderLocation, percent: number) => void;

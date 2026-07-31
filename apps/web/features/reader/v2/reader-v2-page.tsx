'use client';

import type { ReaderPreferences } from '@shuku/reader-core';
import { AlertTriangle, LoaderCircle, RotateCcw } from 'lucide-react';
import Image from 'next/image';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import {
  activateReaderV2User,
  emitReaderDebug,
  getReaderV2Runtime,
  migrateLegacyBrowserReaderState
} from '../../../lib/reader-v2';
import { readDeviceReaderPreferences } from '../../../lib/reader-device-preferences';
import { withBasePath } from '../../../lib/base-path';
import { DEFAULT_READER_THEME, readerThemeSurfaces } from '../reader-theme';
import { fetchReaderBootstrap, type ReaderBootstrap } from './api';
import { resolveRequestedEpubHref } from './epub-direct-target';
import { resolveStartupResume } from './local-resume';
import { ReaderEngineRuntime } from './reader-engine-runtime';
import { useReaderPwaSurface } from './use-reader-pwa-surface';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

const openingStorageKey = 'shuku:reader:opening';

function requireReflowableSourceFormat(bootstrap: ReaderBootstrap) {
  if (bootstrap.readerType !== 'reflowable' || !bootstrap.sourceFormat) {
    throw new Error('小说阅读器启动信息缺少源格式');
  }
  return bootstrap.sourceFormat;
}

type OpeningContext = {
  editionId: string;
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

function pageReducer(state: PageState, action: PageAction): PageState {
  if (action.type !== 'load' && 'requestId' in action && action.requestId !== state.requestId) return state;
  if (action.type === 'load') return { requestId: action.requestId, status: 'loading', bootstrap: null, preferences: null, error: '' };
  if (action.type === 'ready') return { ...state, status: 'ready', bootstrap: action.bootstrap, preferences: action.preferences, error: '' };
  if (action.type === 'error') return { ...state, status: 'error', error: action.error };
  return { ...state, preferences: action.preferences };
}

function readOpeningContext(editionId: string): OpeningContext | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(openingStorageKey);
    if (!raw) return null;
    window.sessionStorage.removeItem(openingStorageKey);
    const value = JSON.parse(raw) as OpeningContext;
    return value.editionId === editionId ? value : null;
  } catch {
    return null;
  }
}

function OpeningCover({ context, ready, background, color, indexProgress }: {
  context: OpeningContext | null;
  ready: boolean;
  background: string;
  color: string;
  indexProgress: { completed: number; total: number; percent: number } | null;
}) {
  const { t: i18nAttribute } = useAttributeI18n();
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
        {indexProgress ? (
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

export function ReaderV2Page({ editionId }: { editionId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedVolumeId = searchParams.get('volume');
  const requestedHref = searchParams.get('href');
  const requestedPage = searchParams.get('page');
  const [state, dispatch] = useReducer(pageReducer, initialPageState);
  const [retry, setRetry] = useState(0);
  const [readerReady, setReaderReady] = useState(false);
  const [indexProgress, setIndexProgress] = useState<{ completed: number; total: number; percent: number } | null>(null);
  const [storageError, setStorageError] = useState('');
  const [openingContext] = useState<OpeningContext | null>(() => readOpeningContext(editionId));
  const requestSequenceRef = useRef(0);
  const runtime = getReaderV2Runtime();
  const activeTheme = state.status === 'error'
    ? 'night'
    : state.preferences?.appearance.theme ?? DEFAULT_READER_THEME;
  const activeSurface = readerThemeSurfaces[activeTheme];
  useReaderPwaSurface(activeTheme);

  const readerHref = useCallback((nextEditionId: string, volumeId?: string | null, pageIndex?: number) => {
    const query = new URLSearchParams();
    if (volumeId) query.set('volume', volumeId);
    if (pageIndex && pageIndex > 0) query.set('page', String(pageIndex));
    return `/reader/${nextEditionId}${query.size ? `?${query}` : ''}`;
  }, []);

  useEffect(() => {
    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;
    const controller = new AbortController();
    setReaderReady(false);
    setIndexProgress(null);
    setStorageError('');
    dispatch({ type: 'load', requestId });

    void (async () => {
      // Snapshot immediately so a fast background sync cannot delete the
      // newest local position between the bootstrap read and reconciliation.
      const pendingAtOpenPromise = runtime.storage.listProgress().catch(() => []);
      let bootstrap = await fetchReaderBootstrap(editionId, requestedVolumeId, controller.signal);
      if (controller.signal.aborted) return;
      let hasDirectTarget = false;
      if (bootstrap.readerType === 'reflowable' && requestedHref) {
        const targetHref = resolveRequestedEpubHref(bootstrap.units, requestedHref);
        if (targetHref) {
          bootstrap = {
            ...bootstrap,
            initialLocation: { kind: 'reflowable', format: requireReflowableSourceFormat(bootstrap), href: targetHref }
          };
          hasDirectTarget = true;
        } else {
          emitReaderDebug('warning', '已忽略不属于当前 EPUB 的章节直达目标', { requestedHref });
        }
      } else if (bootstrap.readerType === 'comic' && requestedPage) {
        const pageIndex = Number(requestedPage);
        const pageExists = Number.isInteger(pageIndex) && bootstrap.pages.some((page) => page.pageIndex === pageIndex);
        if (pageExists && bootstrap.selectedVolume) {
          const pageOrder = bootstrap.pages.findIndex((page) => page.pageIndex === pageIndex);
          const progression = bootstrap.pages.length > 1 ? pageOrder / (bootstrap.pages.length - 1) : 0;
          bootstrap = {
            ...bootstrap,
            initialLocation: { kind: 'comic', volumeId: bootstrap.selectedVolume.id, pageIndex },
            progressPercent: Math.round(progression * 100)
          };
          hasDirectTarget = true;
        } else {
          emitReaderDebug('warning', '已忽略不属于当前漫画卷册的书签页码', { requestedPage });
        }
      }
      activateReaderV2User(bootstrap.userId);
      await migrateLegacyBrowserReaderState({
        currentUserId: bootstrap.userId,
        currentWorkId: bootstrap.edition.workId,
        currentEditionId: bootstrap.edition.id,
        contentFingerprint: bootstrap.contentFingerprint,
        readerKind: bootstrap.readerType,
        volumeId: bootstrap.selectedVolume?.id ?? null
      }, { storage: runtime.storage, repository: runtime.preferences });
      const [pendingAtOpen, pendingAfterMigration] = await Promise.all([
        pendingAtOpenPromise,
        runtime.storage.listProgress().catch(() => [])
      ]);
      const startupResume = resolveStartupResume({
        mutations: [...pendingAtOpen, ...pendingAfterMigration],
        context: bootstrap.readerType === 'reflowable' ? {
          userId: bootstrap.userId,
          editionId: bootstrap.edition.id,
          volumeId: bootstrap.selectedVolume?.id ?? null,
          contentFingerprint: bootstrap.contentFingerprint,
          readerKind: 'reflowable',
          sourceFormat: requireReflowableSourceFormat(bootstrap)
        } : {
          userId: bootstrap.userId,
          editionId: bootstrap.edition.id,
          volumeId: bootstrap.selectedVolume?.id ?? null,
          contentFingerprint: bootstrap.contentFingerprint,
          readerKind: bootstrap.readerType
        },
        initialLocation: bootstrap.initialLocation,
        progressPercent: bootstrap.progressPercent,
        hasDirectTarget
      });
      const localResume = startupResume.localMutation;
      if (localResume) {
        bootstrap = {
          ...bootstrap,
          initialLocation: startupResume.location,
          progressPercent: startupResume.percent
        };
        emitReaderDebug('info', '启动时优先恢复尚未同步的本地阅读位置', {
          editionId: bootstrap.edition.id,
          volumeId: bootstrap.selectedVolume?.id ?? null,
          clientSequence: localResume.clientSequence
        });
      }
      const deviceDefault = readDeviceReaderPreferences(
        bootstrap.userId,
        bootstrap.serverPreferences.settings
      );
      const resolved = await runtime.preferences.resolve(
        bootstrap.userId,
        bootstrap.edition.workId,
        deviceDefault
      );
      if (controller.signal.aborted) return;
      if (bootstrap.resumeFingerprintMismatch) {
        const restoredCurrentLocalPosition = startupResume.source === 'local-pending';
        await runtime.storage.addDiagnostic({
          level: 'warning',
          code: 'content-fingerprint-conflict',
          message: restoredCurrentLocalPosition
            ? '内容已变化，服务端旧阅读位置已隔离；已恢复本机同内容版本的最新位置'
            : '内容已变化，旧阅读位置已隔离，未恢复到新内容',
          data: {
            editionId: bootstrap.edition.id,
            workId: bootstrap.edition.workId,
            contentFingerprint: bootstrap.contentFingerprint,
            reason: bootstrap.resumeDiscardedReason ?? 'content_fingerprint_mismatch',
            resumeSource: startupResume.source
          }
        }).catch(() => undefined);
      }
      emitReaderDebug('info', 'Reader V2 启动完成', {
        editionId: bootstrap.edition.id,
        workId: bootstrap.edition.workId,
        preferences: resolved.source,
        fingerprintMismatch: bootstrap.resumeFingerprintMismatch
      });
      dispatch({ type: 'ready', requestId, bootstrap, preferences: resolved.preferences });
    })().catch((reason) => {
      if (controller.signal.aborted) return;
      dispatch({ type: 'error', requestId, error: reason instanceof Error ? reason.message : '读取阅读器启动信息失败' });
    });

    return () => controller.abort();
  }, [editionId, requestedHref, requestedPage, requestedVolumeId, retry, runtime.preferences, runtime.storage]);

  const savePreferences = useCallback((preferences: ReaderPreferences) => {
    const bootstrap = state.bootstrap;
    if (!bootstrap) return;
    dispatch({ type: 'preferences', preferences });
    setStorageError('');
    void runtime.preferences.save(
      bootstrap.userId,
      bootstrap.edition.workId,
      preferences,
      readDeviceReaderPreferences(bootstrap.userId, bootstrap.serverPreferences.settings)
    ).catch((reason) => {
      setStorageError(reason instanceof Error ? reason.message : '本机阅读设置保存失败');
    });
  }, [runtime.preferences, state.bootstrap]);

  const resetPreferences = useCallback(async () => {
    const bootstrap = state.bootstrap;
    if (!bootstrap) return;
    try {
      const preferences = await runtime.preferences.reset(
        bootstrap.userId,
        bootstrap.edition.workId,
        readDeviceReaderPreferences(bootstrap.userId, bootstrap.serverPreferences.settings)
      );
      dispatch({ type: 'preferences', preferences });
      setStorageError('');
    } catch (reason) {
      setStorageError(reason instanceof Error ? reason.message : '恢复本书默认设置失败');
    }
  }, [runtime.preferences, state.bootstrap]);

  const saveLocation = useCallback((location: Parameters<ReaderV2PageLocationHandler>[0], percent: number) => {
    const bootstrap = state.bootstrap;
    if (!bootstrap) return;
    void runtime.progress.enqueue({
      userId: bootstrap.userId,
      workId: bootstrap.edition.workId,
      editionId: bootstrap.edition.id,
      volumeId: bootstrap.selectedVolume?.id ?? null,
      contentFingerprint: bootstrap.contentFingerprint,
      location,
      percent
    }).catch((reason) => {
      setStorageError(reason instanceof Error ? reason.message : '阅读进度无法写入本机');
    });
  }, [runtime.progress, state.bootstrap]);

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
      {bootstrap && preferences ? (
        <ReaderEngineRuntime
          key={`${bootstrap.edition.id}:${bootstrap.selectedVolume?.id ?? 'root'}:${bootstrap.contentFingerprint}:${retry}`}
          bootstrap={bootstrap}
          preferences={preferences}
          onPreferencesChange={savePreferences}
          onResetPreferences={resetPreferences}
          onLocationChange={saveLocation}
          onBack={() => router.push(`/works/${bootstrap.edition.workId}`)}
          onRetry={() => setRetry((value) => value + 1)}
          onSelectEdition={(nextEditionId) => router.push(readerHref(nextEditionId))}
          onSelectVolume={(volumeId, pageIndex) => router.push(readerHref(bootstrap.edition.id, volumeId, pageIndex))}
          onIndexProgress={setIndexProgress}
          onReady={() => setReaderReady(true)}
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
      <OpeningCover
        context={openingContext}
        ready={readerReady}
        background={activeSurface.background}
        color={activeSurface.color}
        indexProgress={indexProgress}
      />
    </>
  );
}

type ReaderV2PageLocationHandler = (location: import('@shuku/reader-core').ReaderLocation, percent: number) => void;

'use client';

import type { ReaderAdapter, ReaderCommand, ReaderNavigationEntry, ReaderPreferences } from '@shuku/reader-core';
import { LoaderCircle, LockKeyhole, RotateCcw, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { ReaderShell, type ReaderControls, type ReaderNavigationItem, type ReaderShellEvents, type ReaderVolumeNavigation } from '../reader-shell';
import { fetchReaderBookmarks, saveReaderBookmarks, type ReaderBootstrap } from './api';
import { hasReaderBookmark, mergeReaderBookmarks, readReaderBookmarks, readerBookmarkId, readerBookmarkStorageKey, removeReaderBookmark, toggleReaderBookmark, type ReaderBookmark } from './bookmarks';
import { resolveActiveEpubNavigationIndex } from './epub-navigation';
import { locationExtra, locationProgress, preferencesToReaderSettings, readerSettingsToPreferences } from './presentation';
import { useReaderSession } from './use-reader-session';
import { isReaderInteractiveAdapter, type ReaderAdapterInputIntent } from './adapters/reader-interaction';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import type { ReaderBookCache } from '../../../lib/reader/book-cache';

type ReaderEngineRuntimeProps = {
  bootstrap: ReaderBootstrap;
  preferences: ReaderPreferences;
  effectivePreferences: ReaderPreferences;
  onPreferencesChange: (preferences: ReaderPreferences) => void;
  onResetPreferences: () => void | Promise<void>;
  onLocationChange: Parameters<typeof useReaderSession>[0]['onLocationChange'];
  onBack: () => void;
  onRetry: () => void;
  onSelectVolume: (volumeId: string, pageIndex?: number) => void;
  onIndexProgress: (progress: { completed: number; total: number; percent: number } | null) => void;
  onDownloadProgress: (progress: { loadedBytes: number; totalBytes: number | null; percent: number | null } | null) => void;
  onReady: () => void;
  bookCache: ReaderBookCache;
  onStorageWarning: (message: string) => void;
};

type PasswordCapableAdapter = ReaderAdapter & { providePassword: (password: string | null) => boolean };

function canProvidePassword(adapter: ReaderAdapter | null): adapter is PasswordCapableAdapter {
  return Boolean(adapter && 'providePassword' in adapter && typeof (adapter as PasswordCapableAdapter).providePassword === 'function');
}

function bootstrapNavigationItems(bootstrap: ReaderBootstrap, actualTotalPages?: number | null): ReaderNavigationItem[] {
  if (bootstrap.readerType === 'reflowable') {
    return bootstrap.source.kind === 'reflowable' ? adapterNavigationItems(bootstrap.source.navigation) : [];
  }
  const pageCount = actualTotalPages ?? bootstrap.volume.pageCount ?? bootstrap.pages.length ?? 0;
  if (bootstrap.readerType === 'comic' && bootstrap.pages.length) {
    return bootstrap.pages.map((page) => ({ index: page.pageIndex, title: page.title ?? `第 ${page.pageIndex} 页` }));
  }
  return Array.from({ length: pageCount }, (_, index) => ({ index: index + 1, title: `第 ${index + 1} 页` }));
}

function adapterNavigationItems(entries: ReaderNavigationEntry[]): ReaderNavigationItem[] {
  const items: ReaderNavigationItem[] = [];
  const append = (entry: ReaderNavigationEntry) => {
    items.push({
      index: entry.index ?? items.length + 1,
      title: entry.label,
      href: entry.href,
      navigationKey: entry.navigationKey
    });
    entry.children?.forEach(append);
  };
  entries.forEach(append);
  return items;
}

function novelErrorMessage(code: string | undefined, translate: (source: string) => string) {
  if (code === 'NOVEL_UNSUPPORTED_FORMAT') return translate('当前小说格式暂不受支持。');
  if (code === 'NOVEL_DRM_PROTECTED') return translate('文件可能受 DRM 保护，无法打开。');
  if (code === 'NOVEL_PARSE_FAILED') return translate('小说文件无法解析，请检查文件完整性和格式。');
  if (code === 'NOVEL_ENCODING_UNCERTAIN') return translate('无法确定 TXT 文件的文字编码。');
  if (code === 'NOVEL_RESOURCE_FAILED') return translate('小说文件加载失败，请检查网络后重试。');
  if (code === 'NOVEL_SECURITY_REJECTED') return translate('文件包含不安全的内容，已停止打开。');
  return null;
}

function phaseLabel(phase: string | null, kind: ReaderBootstrap['readerType']) {
  if (phase === 'downloading-content') return '首次下载书籍';
  if (phase === 'generating-pagination') return '正在建立全书位置索引';
  if (phase === 'loading-font') return '正在准备阅读字体';
  if (phase === 'rendering') return kind === 'pdf' ? '正在渲染 PDF' : '正在排版正文';
  return '正在加载阅读内容';
}

export function ReaderEngineRuntime({
  bootstrap,
  preferences,
  effectivePreferences,
  onPreferencesChange,
  onResetPreferences,
  onLocationChange,
  onBack,
  onRetry,
  onSelectVolume,
  onIndexProgress,
  onDownloadProgress,
  onReady,
  bookCache,
  onStorageWarning
}: ReaderEngineRuntimeProps) {
  const { t: i18nAttribute } = useAttributeI18n();
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const [adapter, setAdapter] = useState<ReaderAdapter | null>(null);
  const [adapterLoadError, setAdapterLoadError] = useState('');
  const [passwordReason, setPasswordReason] = useState<'need-password' | 'incorrect-password' | null>(null);
  const [password, setPassword] = useState('');
  const [bookmarks, setBookmarks] = useState<ReaderBookmark[]>([]);
  const bookmarkSyncReadyRef = useRef(false);
  const executeRef = useRef<(command: ReaderCommand) => Promise<boolean>>(async () => false);
  const shellEventsRef = useRef<ReaderShellEvents | null>(null);
  const interactionBlockedRef = useRef(true);
  const onSelectVolumeRef = useRef(onSelectVolume);
  onSelectVolumeRef.current = onSelectVolume;

  useEffect(() => {
    if (!container) return undefined;
    let active = true;
    let created: ReaderAdapter | null = null;
    setAdapter(null);
    setAdapterLoadError('');
    container.replaceChildren();

    void (async () => {
      const openNextVolume = () => {
        const currentIndex = bootstrap.availableVolumes.findIndex((volume) => volume.id === bootstrap.volume.id);
        const nextVolume = currentIndex >= 0 ? bootstrap.availableVolumes[currentIndex + 1] : undefined;
        if (nextVolume) onSelectVolumeRef.current(nextVolume.id);
      };
      const handleAdapterInputIntent = (intent: ReaderAdapterInputIntent) => {
        const blocked = interactionBlockedRef.current || Boolean(shellEventsRef.current?.isInteractionBlocked());
        if (intent.type === 'escape') {
          shellEventsRef.current?.escape();
          return false;
        }
        if (blocked) return false;
        if (intent.type === 'toggle-controls') {
          shellEventsRef.current?.toggleControls();
          return false;
        }
        return executeRef.current(intent.command);
      };
      if (bootstrap.readerType === 'reflowable') {
        const adapterModule = await import('./adapters/foliate-adapter');
        created = adapterModule.createFoliateAdapter({
          container,
          title: bootstrap.book.title,
          userId: bootstrap.userId,
          bookCache,
          onCacheWarning: () => onStorageWarning(i18nAttribute('书籍已打开，但本机存储空间不足；下次阅读时需要重新下载。')),
          onEndOfVolume: openNextVolume,
          onInputIntent: handleAdapterInputIntent
        });
      } else if (bootstrap.readerType === 'comic') {
        const adapterModule = await import('./adapters/comic-adapter');
        created = adapterModule.createComicAdapter({
          container,
          onInputIntent: handleAdapterInputIntent,
          onEndOfVolume: openNextVolume,
          initialPages: bootstrap.pages.map((page) => ({
            pageIndex: page.pageIndex,
            title: page.title ?? undefined,
            mimeType: page.mimeType ?? undefined,
            width: page.width ?? undefined,
            height: page.height ?? undefined,
            size: page.size ?? undefined
          }))
        });
      } else {
        const adapterModule = await import('./adapters/pdf-adapter');
        created = adapterModule.createPdfAdapter({ container });
      }
      if (!active) {
        void created.dispose();
        return;
      }
      setAdapter(created);
    })().catch((reason) => {
      if (active) {
        setAdapter(null);
        setAdapterLoadError(reason instanceof Error ? reason.message : '阅读引擎加载失败，请检查网络后重试。');
      }
    });

    return () => {
      active = false;
      if (created) void created.dispose();
      container.replaceChildren();
    };
  }, [bookCache, bootstrap.availableVolumes, bootstrap.book.title, bootstrap.contentFingerprint, bootstrap.pages, bootstrap.readerType, bootstrap.userId, bootstrap.volume.id, container, i18nAttribute, onStorageWarning]);

  const session = useReaderSession({
    adapter,
    source: bootstrap.source,
    initialLocation: bootstrap.initialLocation,
    preferences: effectivePreferences,
    onLocationChange,
    onExternalLink: (href) => window.open(href, '_blank', 'noopener,noreferrer'),
    onPasswordRequired: (reason) => {
      onReady();
      setPassword('');
      setPasswordReason(reason);
    }
  });
  const sessionControls = session.controls;
  const sessionExecute = session.execute;
  executeRef.current = sessionExecute;
  const interactionBlocked = !adapter
    || session.state.lifecycle === 'bootstrapping'
    || session.state.lifecycle === 'loading'
    || session.state.lifecycle === 'error'
    || session.state.phase === 'loading-font'
    || session.state.phase === 'generating-pagination'
    || Boolean(passwordReason);
  interactionBlockedRef.current = interactionBlocked;
  const horizontalPaging = isReaderInteractiveAdapter(adapter)
    ? adapter.getInteractionPolicy().horizontalPaging
    : 'shell-discrete';

  useEffect(() => {
    if (
      session.state.lifecycle === 'ready'
      || session.state.lifecycle === 'error'
      || adapterLoadError
    ) onReady();
  }, [adapterLoadError, onReady, session.state.lifecycle]);

  useEffect(() => {
    onIndexProgress(session.state.phase === 'generating-pagination'
      ? session.state.paginationProgress ?? { completed: 0, total: 0, percent: 0 }
      : null);
  }, [onIndexProgress, session.state.paginationProgress, session.state.phase]);

  useEffect(() => {
    onDownloadProgress(session.state.phase === 'downloading-content'
      ? session.state.downloadProgress ?? { loadedBytes: 0, totalBytes: null, percent: null }
      : null);
  }, [onDownloadProgress, session.state.downloadProgress, session.state.phase]);

  const totalHint = bootstrap.readerType === 'reflowable'
    ? null
    : (session.state.totalPages ?? bootstrap.volume.pageCount ?? bootstrap.pages.length) || null;
  const currentPercent = session.state.location ? session.state.percent : bootstrap.progressPercent;
  const progress = locationProgress(session.state.location ?? bootstrap.initialLocation, currentPercent, totalHint);
  const progressExtra = locationExtra(session.state.location ?? bootstrap.initialLocation);
  const currentLocation = session.state.location ?? bootstrap.initialLocation;
  const currentVolumeIndex = bootstrap.availableVolumes.findIndex((volume) => volume.id === bootstrap.volume.id);
  const hasNextVolume = currentVolumeIndex >= 0 && currentVolumeIndex < bootstrap.availableVolumes.length - 1;
  const adapterCapabilities = session.state.capabilities ?? bootstrap.capabilities;
  const effectiveCapabilities = hasNextVolume && !adapterCapabilities.canGoNext
    ? { ...adapterCapabilities, canGoNext: true }
    : adapterCapabilities;
  const settings = {
    ...preferencesToReaderSettings(effectivePreferences),
    manualTheme: preferences.appearance.theme
  };
  const items = useMemo(() => {
    const adapterItems = session.state.navigationReady ? adapterNavigationItems(session.state.navigationItems) : [];
    return adapterItems.length > 0 ? adapterItems : bootstrapNavigationItems(bootstrap, session.state.totalPages);
  }, [bootstrap, session.state.navigationItems, session.state.navigationReady, session.state.totalPages]);
  const bookmarkStorageKey = useMemo(() => readerBookmarkStorageKey(
    bootstrap.userId,
    bootstrap.volume.id,
    bootstrap.contentFingerprint
  ), [bootstrap.contentFingerprint, bootstrap.userId, bootstrap.volume.id]);

  useEffect(() => {
    const controller = new AbortController();
    bookmarkSyncReadyRef.current = false;
    let localBookmarks: ReaderBookmark[] = [];
    try {
      const current = readReaderBookmarks(window.localStorage.getItem(bookmarkStorageKey));
      localBookmarks = current;
      setBookmarks(localBookmarks);
    } catch {
      setBookmarks([]);
    }
    fetchReaderBookmarks(bootstrap.volume.id, bootstrap.contentFingerprint, controller.signal)
      .then((serverBookmarks) => {
        setBookmarks((current) => {
          const next = mergeReaderBookmarks(current, serverBookmarks);
          try {
            window.localStorage.setItem(bookmarkStorageKey, JSON.stringify(next));
          } catch {
            // Server state remains authoritative when local storage is unavailable.
          }
          bookmarkSyncReadyRef.current = true;
          if (JSON.stringify(next) !== JSON.stringify(serverBookmarks)) {
            void saveReaderBookmarks(bootstrap.volume.id, bootstrap.contentFingerprint, next).catch(() => undefined);
          }
          return next;
        });
      })
      .catch((reason) => {
        if (!(reason instanceof DOMException && reason.name === 'AbortError')) bookmarkSyncReadyRef.current = true;
      });
    return () => controller.abort();
  }, [bookmarkStorageKey, bootstrap.contentFingerprint, bootstrap.volume.id]);

  const persistBookmarks = useCallback((update: (current: ReaderBookmark[]) => ReaderBookmark[]) => {
    setBookmarks((current) => {
      const next = update(current);
      try {
        window.localStorage.setItem(bookmarkStorageKey, JSON.stringify(next));
      } catch {
        // The visible state still works when private browsing blocks storage.
      }
      if (bookmarkSyncReadyRef.current) {
        void saveReaderBookmarks(bootstrap.volume.id, bootstrap.contentFingerprint, next).catch(() => undefined);
      }
      return next;
    });
  }, [bookmarkStorageKey, bootstrap.contentFingerprint, bootstrap.volume.id]);

  const currentBookmarkLabel = useMemo(() => {
    if (currentLocation?.kind === 'comic') {
      return bootstrap.volume.title ? `${bootstrap.volume.title} · ${progress.label}` : progress.label;
    }
    if (currentLocation?.kind !== 'reflowable' && currentLocation?.kind !== 'epub') return progress.label;
    const activeIndex = resolveActiveEpubNavigationIndex(
      items,
      currentLocation.href,
      currentLocation.kind === 'epub' ? currentLocation.spineIndex : undefined
    );
    const chapter = activeIndex === null ? null : items[activeIndex];
    return chapter ? `${chapter.title} · 全书 ${Math.round(progress.percent)}%` : progress.label;
  }, [bootstrap.volume.title, currentLocation, items, progress.label, progress.percent]);

  const toggleCurrentBookmark = useCallback(() => {
    if (!currentLocation) return;
    persistBookmarks((current) => toggleReaderBookmark(current, {
        location: currentLocation,
        label: currentBookmarkLabel,
        percent: progress.percent,
        createdAt: new Date().toISOString()
      }));
  }, [currentBookmarkLabel, currentLocation, persistBookmarks, progress.percent]);

  const removeBookmark = useCallback((id: string) => {
    persistBookmarks((current) => removeReaderBookmark(current, id));
  }, [persistBookmarks]);

  const jumpToBookmark = useCallback(async (bookmark: ReaderBookmark) => {
    if (bookmark.location.kind === 'comic' && bookmark.location.volumeId !== bootstrap.volume.id) {
      onSelectVolume(bookmark.location.volumeId, bookmark.location.pageIndex);
      return;
    }
    await sessionExecute({ type: 'go-to-location', location: bookmark.location });
  }, [bootstrap.volume.id, onSelectVolume, sessionExecute]);

  const controls: ReaderControls = useMemo(() => ({
    next: async () => { await sessionControls.next(); },
    prev: async () => { await sessionControls.prev(); },
    jumpToProgress: async (percent) => { await sessionControls.jumpToProgress(percent); },
    jumpToHref: async (href) => { await sessionControls.jumpToHref(href); },
    jumpToIndex: async (index) => { await sessionControls.jumpToIndex(index); }
  }), [sessionControls]);

  const volumeNavigation: ReaderVolumeNavigation = useMemo(() => ({
    volumeSections: bootstrap.availableVolumes.map((volume) => ({
      id: volume.id,
      title: volume.title,
      pageCount: bootstrap.readerType === 'reflowable'
        ? volume.chapterCount ?? 0
        : volume.pageCount ?? 0
    })),
    pages: items,
    currentVolumeId: bootstrap.volume.id,
    loading: false,
    onSelectVolume,
    onSelectItem: (item) => {
      if (item.href) void sessionControls.jumpToHref(item.href);
      else void sessionControls.jumpToIndex(item.index);
    }
  }), [bootstrap, items, onSelectVolume, sessionControls]);

  function submitPassword(event: FormEvent) {
    event.preventDefault();
    if (!canProvidePassword(adapter) || !password) return;
    adapter.providePassword(password);
    setPassword('');
    setPasswordReason(null);
  }

  return (
    <ReaderShell
      readerType={bootstrap.readerType}
      progress={progress}
      progressExtra={progressExtra}
      controls={controls}
      settings={settings}
      capabilities={effectiveCapabilities}
      readingDirection={bootstrap.readerType === 'comic'
        ? effectivePreferences.comic.direction
        : (session.state.capabilities?.readingDirection ?? bootstrap.capabilities.readingDirection)}
      onBack={onBack}
      onSettingsChange={(next) => {
        const mapped = readerSettingsToPreferences(next);
        onPreferencesChange(preferences.appearance.themeMode === 'system' && next.themeMode === 'system'
          ? { ...mapped, appearance: { ...mapped.appearance, theme: preferences.appearance.theme } }
          : mapped);
      }}
      onResetSettings={onResetPreferences}
      interactionBlocked={interactionBlocked}
      horizontalPaging={horizontalPaging}
      navigationItems={items}
      volumeNavigation={volumeNavigation}
      bookmarkActive={hasReaderBookmark(bookmarks, currentLocation)}
      currentBookmarkId={readerBookmarkId(currentLocation)}
      bookmarks={bookmarks}
      canBookmark={Boolean(currentLocation)}
      onToggleBookmark={toggleCurrentBookmark}
      onJumpBookmark={jumpToBookmark}
      onRemoveBookmark={removeBookmark}
    >
      {(events) => {
        shellEventsRef.current = events;
        return (
          <div className="relative h-full min-h-0 w-full overflow-hidden">
            <div ref={setContainer} className="h-full min-h-0 w-full" aria-label={i18nAttribute("{value0} 阅读内容", { value0: bootstrap.book.title })} />
            {(!adapter
              || session.state.lifecycle === 'bootstrapping'
              || session.state.lifecycle === 'loading'
              || session.state.phase === 'loading-font') && !adapterLoadError ? (
              <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 bg-black/20 px-6 text-center backdrop-blur-[2px]">
                <LoaderCircle className="animate-spin" size={28} />
                <div className="text-sm">{phaseLabel(session.state.phase, bootstrap.readerType)}</div>
                {session.state.phase === 'generating-pagination' ? (
                  <div className="w-full max-w-sm">
                    <p className="text-xs opacity-70"><I18nText>首次打开需要完成一次，之后将直接进入阅读。</I18nText></p>
                    <div
                      className="mt-4 h-2 overflow-hidden rounded-full bg-white/15"
                      role="progressbar"
                      aria-label={i18nAttribute("全书位置索引进度")}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.round(session.state.paginationProgress?.percent ?? 0)}
                    >
                      <div
                        className="h-full rounded-full bg-white transition-[width] duration-150"
                        style={{ width: `${session.state.paginationProgress?.percent ?? 0}%` }}
                      />
                    </div>
                    <div className="mt-2 text-xs tabular-nums opacity-75">
                      {session.state.paginationProgress
                        ? i18nAttribute("已处理 {value0} / {value1} 章 · {value2}%", { value0: session.state.paginationProgress.completed, value1: session.state.paginationProgress.total, value2: Math.round(session.state.paginationProgress.percent) })
                        : i18nAttribute("正在准备章节索引…")}
                    </div>
                    <button type="button" onClick={onBack} className="mt-4 min-h-11 rounded-xl bg-white/10 px-4 text-sm transition hover:bg-white/15"><I18nText>取消并返回书库</I18nText></button>
                  </div>
                ) : null}
              </div>
            ) : null}
            {session.state.lifecycle === 'error' || adapterLoadError ? (
              <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/45 p-6 text-center backdrop-blur-sm">
                <div className="w-full max-w-sm rounded-2xl bg-slate-950/90 p-5 text-white shadow-2xl">
                  <div className="text-base font-semibold"><I18nText>阅读器加载失败</I18nText></div>
                  <p className="mt-2 text-sm text-slate-300">{
                    novelErrorMessage(session.state.error?.code, i18nAttribute)
                      || adapterLoadError
                      || session.state.error?.message
                      || i18nAttribute("请检查网络或文件是否仍然存在。")
                  }</p>
                  <div className="mt-4 grid grid-cols-2 gap-2">
                    <button type="button" onClick={onBack} className="min-h-11 rounded-xl bg-white/10 px-3 text-sm">{
                      i18nAttribute("返回书库")
                    }</button>
                    <button type="button" onClick={onRetry} className="flex min-h-11 items-center justify-center gap-2 rounded-xl bg-blue-600 px-3 text-sm"><RotateCcw size={16} /><I18nText>重试</I18nText></button>
                  </div>
                </div>
              </div>
            ) : null}
            {passwordReason ? (
              <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/60 p-6 backdrop-blur-sm" data-reader-control="true">
                <form
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby="reader-pdf-password-title"
                  onSubmit={submitPassword}
                  onKeyDown={(event) => {
                    event.stopPropagation();
                    if (event.key === 'Tab') {
                      const form = event.currentTarget;
                      const items = Array.from(form.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'));
                      const first = items[0];
                      const last = items[items.length - 1];
                      if (event.shiftKey && document.activeElement === first) {
                        event.preventDefault();
                        last?.focus();
                      } else if (!event.shiftKey && document.activeElement === last) {
                        event.preventDefault();
                        first?.focus();
                      }
                      return;
                    }
                    if (event.key === 'Escape') {
                      event.preventDefault();
                      if (canProvidePassword(adapter)) adapter.providePassword(null);
                      setPasswordReason(null);
                    }
                  }}
                  className="w-full max-w-sm rounded-2xl bg-slate-950 p-5 text-white shadow-2xl"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div id="reader-pdf-password-title" className="flex items-center gap-2 font-semibold"><LockKeyhole size={18} /><I18nText>PDF 需要密码</I18nText></div>
                    <button type="button" aria-label={i18nAttribute("取消输入密码")} onClick={() => { if (canProvidePassword(adapter)) adapter.providePassword(null); setPasswordReason(null); }} className="flex h-10 w-10 items-center justify-center rounded-full hover:bg-white/10"><X size={17} /></button>
                  </div>
                  <p className="mt-2 text-sm text-slate-300">{passwordReason === 'incorrect-password' ? i18nAttribute("密码不正确，请重新输入。") : i18nAttribute("密码仅用于本次打开，不会保存。")}</p>
                  <input autoFocus type="password" value={password} onChange={(event) => setPassword(event.target.value)} className="mt-4 h-11 w-full rounded-xl border border-white/15 bg-white/10 px-3 outline-none focus:border-blue-400" />
                  <button type="submit" disabled={!password} className="mt-3 min-h-11 w-full rounded-xl bg-blue-600 px-4 text-sm font-medium disabled:opacity-50"><I18nText>打开 PDF</I18nText></button>
                </form>
              </div>
            ) : null}
          </div>
        );
      }}
    </ReaderShell>
  );
}

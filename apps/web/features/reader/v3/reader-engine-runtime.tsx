'use client';

import type { ReaderAdapter, ReaderCommand, ReaderPreferences } from '@shuku/reader-core';
import { LoaderCircle, LockKeyhole, RotateCcw, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { ReaderShell, type ReaderControls, type ReaderNavigationItem, type ReaderShellEvents, type ReaderResourceNavigation } from '../reader-shell';
import { fetchReaderBookmarks, saveReaderBookmarks, type ReaderBootstrap } from './api';
import { hasReaderBookmark, mergeReaderBookmarks, readReaderBookmarks, readerBookmarkId, readerBookmarkStorageKey, removeReaderBookmark, toggleReaderBookmark, type ReaderBookmark } from './bookmarks';
import { resolveActiveEpubNavigationIndex } from './epub-navigation';
import { locationExtra, locationProgress, preferencesToReaderSettings, readerSettingsToPreferences } from './presentation';
import { useReaderSession } from './use-reader-session';
import { isReaderInteractiveAdapter, type ReaderAdapterInputIntent } from './adapters/reader-interaction';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import { projectReadiumEffectivePreferences } from './adapters/readium-presentation';

type ReaderEngineRuntimeProps = {
  bootstrap: ReaderBootstrap;
  preferences: ReaderPreferences;
  effectivePreferences: ReaderPreferences;
  onPreferencesChange: (preferences: ReaderPreferences) => void;
  onResetPreferences: () => void | Promise<void>;
  onLocationChange: Parameters<typeof useReaderSession>[0]['onLocationChange'];
  onBack: () => void;
  onRetry: () => void;
  onSelectResource: (resourceId: string, pageIndex?: number) => void;
  onIndexProgress: (progress: { completed: number; total: number; percent: number } | null) => void;
  onReady: () => void;
  onStorageWarning: (message: string) => void;
  externalNavigation?: { id: number; location: import('@shuku/reader-core').ReaderLocation } | null;
  onExternalNavigationResult?: (id: number, accepted: boolean) => void;
};

type PasswordCapableAdapter = ReaderAdapter & { providePassword: (password: string | null) => boolean };

function canProvidePassword(adapter: ReaderAdapter | null): adapter is PasswordCapableAdapter {
  return Boolean(adapter && 'providePassword' in adapter && typeof (adapter as PasswordCapableAdapter).providePassword === 'function');
}

function bootstrapNavigationItems(bootstrap: ReaderBootstrap): ReaderNavigationItem[] {
  if (bootstrap.readerType !== 'comic') {
    return bootstrap.units.map((unit) => ({
      index: unit.index,
      title: unit.title,
      href: unit.href ?? undefined,
      navigationKey: unit.id
    }));
  }
  return bootstrap.pages.map((page) => ({
    index: page.pageIndex,
    title: page.title ?? String(page.pageIndex + 1),
    href: page.resourceHref,
    navigationKey: bootstrap.units.find(
      (unit) => unit.metadata.pageIndex === page.pageIndex
    )?.id
  }));
}

function readerErrorMessage(code: string | undefined, translate: (source: string) => string) {
  if (code === 'PUBLICATION_CHANGED' || code === 'PUBLICATION_RESOURCE_CHANGED') return translate('出版物已更新，请重新打开。');
  if (code === 'PUBLICATION_RESOURCE_TOO_LARGE' || code === 'RESPONSE_TOO_LARGE') return translate('当前章节超过在线阅读的安全上限，无法打开。');
  if (code === 'RESPONSE_LENGTH_INVALID' || code === 'RESPONSE_STREAM_MISSING') return translate('章节响应无效，请重试。');
  if (code === 'PUBLICATION_RESOURCE_UNAVAILABLE') return translate('章节资源无法读取，请检查网络后重试。');
  if (code === 'READIUM_PUBLICATION_SECURITY_PROFILE_MISSING') return translate('文件包含不安全的内容，已停止打开。');
  if (code === 'READER_EXACT_RESTORE_UNVERIFIED') return translate('无法精确恢复到另一设备的位置');
  if (code === 'READIUM_PUBLICATION_ENDPOINT_UNAVAILABLE') return translate('服务器尚未提供 Readium Publication，无法打开此书。');
  if (code === 'NOVEL_UNSUPPORTED_FORMAT') return translate('当前小说格式暂不受支持。');
  if (code === 'NOVEL_DRM_PROTECTED') return translate('文件可能受 DRM 保护，无法打开。');
  if (code === 'NOVEL_PARSE_FAILED') return translate('小说文件无法解析，请检查文件完整性和格式。');
  if (code === 'NOVEL_ENCODING_UNCERTAIN') return translate('无法确定 TXT 文件的文字编码。');
  if (code === 'NOVEL_RESOURCE_FAILED') return translate('小说文件加载失败，请检查网络后重试。');
  if (code === 'NOVEL_SECURITY_REJECTED') return translate('文件包含不安全的内容，已停止打开。');
  if (code === 'RESOURCE_FORMAT_UNSUPPORTED') return translate('当前文件格式尚未开放阅读支持。');
  if (code === 'READER_FORMAT_MORPHOLOGY_MISMATCH') return translate('文件格式与阅读器类型不匹配。');
  if (code === 'PDF_ENCRYPTED' || code === 'PDF_PASSWORD_CANCELLED') return translate('加密或密码保护的 PDF 暂不支持阅读。');
  if (code === 'PDF_INVALID') return translate('PDF 文件已损坏或格式无效。');
  if (code === 'PDF_RANGE_UNSUPPORTED') return translate('服务器不支持 PDF 按需读取，无法在线打开。');
  if (code === 'PDF_RANGE_INVALID') return translate('PDF 字节区间响应无效，请重试。');
  if (code === 'PDF_RESOURCE_CHANGED') return translate('PDF 文件已更新，请重新打开。');
  if (code === 'NETWORK_UNAVAILABLE') return translate('网络不可用，无法加载 PDF 页面。');
  if (code === 'PDF_CACHE_IO') return translate('PDF 缓存读写失败。');
  if (code === 'PDF_PAGE_LOAD_FAILED') return translate('PDF 页面加载失败。');
  if (code === 'PDF_RENDER_FAILED') return translate('PDF 页面渲染失败。');
  if (code === 'OUT_OF_MEMORY_RISK') return translate('PDF 页面尺寸过大，无法安全渲染。');
  if (code === 'COMIC_INDEX_INVALID') return translate('漫画页面索引无效或尚未准备完成。');
  return null;
}

function phaseLabel(phase: string | null, kind: ReaderBootstrap['readerType']) {
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
  onSelectResource,
  onIndexProgress,
  onReady,
  onStorageWarning,
  externalNavigation = null,
  onExternalNavigationResult
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
  const onSelectResourceRef = useRef(onSelectResource);
  onSelectResourceRef.current = onSelectResource;
  const runtimePreferences = useMemo(
    () => bootstrap.readerType === 'reflowable'
      ? projectReadiumEffectivePreferences(effectivePreferences)
      : effectivePreferences,
    [bootstrap.readerType, effectivePreferences]
  );

  useEffect(() => {
    if (!container) return undefined;
    let active = true;
    let created: ReaderAdapter | null = null;
    setAdapter(null);
    setAdapterLoadError('');
    container.replaceChildren();

    void (async () => {
      const openNextResource = async () => {
        const currentIndex = bootstrap.availableResources.findIndex((resource) => resource.id === bootstrap.resource.id);
        const nextResource = currentIndex >= 0 ? bootstrap.availableResources[currentIndex + 1] : undefined;
        if (!nextResource) return false;
        onSelectResourceRef.current(nextResource.id);
        return true;
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
        const adapterModule = await import('./adapters/readium-adapter');
        created = adapterModule.createReadiumWebReaderAdapter({
          container,
          initialHref: bootstrap.units[0]?.href ?? null,
          onInputIntent: handleAdapterInputIntent,
          onEndOfResource: openNextResource
        });
      } else if (bootstrap.readerType === 'comic') {
        const adapterModule = await import('./adapters/comic-adapter');
        created = adapterModule.createComicAdapter({
          container,
          onInputIntent: handleAdapterInputIntent,
          onEndOfResource: openNextResource,
          initialPages: bootstrap.pages.map((page) => ({
            pageIndex: page.pageIndex,
            resourceHref: page.resourceHref,
            title: page.title ?? undefined,
            mimeType: page.mimeType ?? undefined,
            width: page.width ?? undefined,
            height: page.height ?? undefined,
            size: page.size ?? undefined
          }))
        });
      } else {
        const adapterModule = await import('./adapters/pdf-adapter');
        const pdfAsset = bootstrap.assets.find((asset) => asset.mimeType.toLowerCase() === 'application/pdf') ?? bootstrap.assets[0];
        if (!pdfAsset || pdfAsset.sizeBytes <= 0) throw new Error('PDF_INVALID');
        created = adapterModule.createPdfAdapter({
          container,
          rangeAccess: {
            url: pdfAsset.url,
            length: pdfAsset.sizeBytes,

          }
        });
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
  }, [bootstrap.availableResources, bootstrap.book.title, bootstrap.assets, bootstrap.pages, bootstrap.readerType, bootstrap.units, bootstrap.userId, bootstrap.resource.id, container, i18nAttribute, onStorageWarning]);

  const session = useReaderSession({
    adapter,
    source: bootstrap.source,
    initialLocation: bootstrap.initialLocation,
    preferences: runtimePreferences,
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
    if (!externalNavigation || session.state.lifecycle !== 'ready') return;
    let active = true;
    void sessionExecute({ type: 'go-to-location', location: externalNavigation.location })
      .then((accepted) => { if (active) onExternalNavigationResult?.(externalNavigation.id, accepted); })
      .catch(() => { if (active) onExternalNavigationResult?.(externalNavigation.id, false); });
    return () => { active = false; };
  }, [externalNavigation, onExternalNavigationResult, session.state.lifecycle, sessionExecute]);

  useEffect(() => {
    onIndexProgress(session.state.phase === 'generating-pagination'
      ? session.state.paginationProgress ?? { completed: 0, total: 0, percent: 0 }
      : null);
  }, [onIndexProgress, session.state.paginationProgress, session.state.phase]);



  const totalHint = bootstrap.readerType === 'reflowable'
    ? null
    : (session.state.totalPages ?? bootstrap.resource.pageCount ?? bootstrap.pages.length) || null;
  const currentPercent = session.state.location ? session.state.percent : bootstrap.progressPercent;
  const progress = locationProgress(session.state.location ?? bootstrap.initialLocation, currentPercent, totalHint);
  const progressExtra = locationExtra(session.state.location ?? bootstrap.initialLocation);
  const currentLocation = session.state.location ?? bootstrap.initialLocation;
  const currentResourceIndex = bootstrap.availableResources.findIndex((resource) => resource.id === bootstrap.resource.id);
  const hasNextResource = currentResourceIndex >= 0 && currentResourceIndex < bootstrap.availableResources.length - 1;
  const adapterCapabilities = session.state.capabilities ?? bootstrap.capabilities;
  const effectiveCapabilities = hasNextResource && !adapterCapabilities.canGoNext
    ? { ...adapterCapabilities, canGoNext: true }
    : adapterCapabilities;
  const settings = {
    ...preferencesToReaderSettings(runtimePreferences),
    manualTheme: preferences.appearance.theme
  };
  const items = useMemo(() => bootstrapNavigationItems(bootstrap), [bootstrap]);
  const bookmarkStorageKey = useMemo(() => readerBookmarkStorageKey(
    bootstrap.userId,
    bootstrap.resource.id
  ), [bootstrap.userId, bootstrap.resource.id]);

  useEffect(() => {
    const controller = new AbortController();
    const format = bootstrap.source.kind === 'reflowable' ? bootstrap.source.sourceFormat : null;
    bookmarkSyncReadyRef.current = false;
    let localBookmarks: ReaderBookmark[] = [];
    try {
      const current = readReaderBookmarks(window.localStorage.getItem(bookmarkStorageKey));
      localBookmarks = current;
      setBookmarks(localBookmarks);
    } catch {
      setBookmarks([]);
    }
    fetchReaderBookmarks(bootstrap.resource.id, format, controller.signal)
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
            void saveReaderBookmarks(bootstrap.resource.id, format, next).catch(() => undefined);
          }
          return next;
        });
      })
      .catch((reason) => {
        if (!(reason instanceof DOMException && reason.name === 'AbortError')) bookmarkSyncReadyRef.current = true;
      });
    return () => controller.abort();
  }, [bookmarkStorageKey, bootstrap.source, bootstrap.resource.id]);

  const persistBookmarks = useCallback((update: (current: ReaderBookmark[]) => ReaderBookmark[]) => {
    setBookmarks((current) => {
      const next = update(current);
      try {
        window.localStorage.setItem(bookmarkStorageKey, JSON.stringify(next));
      } catch {
        // The visible state still works when private browsing blocks storage.
      }
      if (bookmarkSyncReadyRef.current) {
        const format = bootstrap.source.kind === 'reflowable' ? bootstrap.source.sourceFormat : null;
        void saveReaderBookmarks(bootstrap.resource.id, format, next).catch(() => undefined);
      }
      return next;
    });
  }, [bookmarkStorageKey, bootstrap.source, bootstrap.resource.id]);

  const currentBookmarkLabel = useMemo(() => {
    if (currentLocation?.kind === 'comic') {
      return bootstrap.resource.title ? `${bootstrap.resource.title} · ${progress.label}` : progress.label;
    }
    if (currentLocation?.kind !== 'reflowable') return progress.label;
    const activeIndex = resolveActiveEpubNavigationIndex(
      items,
      currentLocation.href,
      currentLocation.spineIndex
    );
    const chapter = activeIndex === null ? null : items[activeIndex];
    return chapter ? `${chapter.title} · 全书 ${Math.round(progress.percent)}%` : progress.label;
  }, [bootstrap.resource.title, currentLocation, items, progress.label, progress.percent]);

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
    if (bookmark.location.kind === 'comic' && bookmark.location.resourceId !== bootstrap.resource.id) {
      onSelectResource(bookmark.location.resourceId, bookmark.location.pageIndex);
      return;
    }
    await sessionExecute({ type: 'go-to-location', location: bookmark.location });
  }, [bootstrap.resource.id, onSelectResource, sessionExecute]);

  const controls: ReaderControls = useMemo(() => ({
    next: () => sessionControls.next(),
    prev: () => sessionControls.prev(),
    jumpToProgress: (percent) => sessionControls.jumpToProgress(percent),
    jumpToHref: (href) => sessionControls.jumpToHref(href),
    jumpToIndex: (index) => sessionControls.jumpToIndex(index)
  }), [sessionControls]);

  const resourceNavigation: ReaderResourceNavigation = useMemo(() => ({
    resourceSections: bootstrap.availableResources.map((resource) => ({
      id: resource.id,
      title: resource.title,
      pageCount: bootstrap.readerType === 'reflowable'
        ? resource.chapterCount ?? 0
        : resource.pageCount ?? 0
    })),
    pages: items,
    currentResourceId: bootstrap.resource.id,
    loading: false,
    onSelectResource,
    onSelectItem: (item) => {
      if (bootstrap.readerType === 'reflowable' && item.href) void sessionControls.jumpToHref(item.href);
      else void sessionControls.jumpToIndex(item.index);
    }
  }), [bootstrap, items, onSelectResource, sessionControls]);

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
        ? runtimePreferences.comic.direction
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
      resourceNavigation={resourceNavigation}
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
          <div className={`relative h-full min-h-0 w-full overflow-hidden ${bootstrap.readerType === 'reflowable'
            ? 'box-border py-[clamp(32px,5vh,64px)] max-[640px]:py-[clamp(16px,2.5vh,32px)]'
            : ''}`}>
            <div
              ref={setContainer}
              className={`h-full min-h-0 w-full ${bootstrap.readerType === 'reflowable'
                ? 'relative mx-auto [&>.readium-navigator-iframe]:inset-0 [&>.readium-navigator-iframe]:h-full [&>.readium-navigator-iframe]:w-full [&>.readium-navigator-iframe]:border-0'
                : ''}`}
              aria-label={i18nAttribute("{value0} 阅读内容", { value0: bootstrap.book.title })}
            />
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
                    readerErrorMessage(session.state.error?.code, i18nAttribute)
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

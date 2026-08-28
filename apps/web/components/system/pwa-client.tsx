'use client';

import { Bug, Clipboard, Download, RefreshCw, Trash2, Wifi, WifiOff, X } from 'lucide-react';
import Image from 'next/image';
import { usePathname } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { clearPrivatePwaData } from '../../lib/pwa/progressQueue';
import {
  checkFrontendResourceVersion,
  purgeFrontendResourcesAndActivate,
  waitForLatestWorker
} from '../../lib/pwa/frontend-resource-update';
import {
  probeApplicationReachability,
  resolveApplicationOnline
} from '../../lib/pwa/network-availability';
import { prepareForPwaUpdate } from '../../lib/pwa/update-coordination';
import { activateReaderUser, clearPrivateReaderData, deactivateReaderUser, getReaderRuntime, startReaderRuntime, stopReaderRuntime } from '../../lib/reader';
import { withBasePath } from '../../lib/base-path';
import { PRODUCT_NAME } from '../../lib/brand';
import { clearCurrentUserNamespace, currentUserId, setCurrentUserNamespace, userDevicePreferenceKey } from '../../lib/user-preferences';
import { useAppSession } from '../layout/app-session-context';
import { cn } from '../ui/cn';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import { useI18n as useExpressionI18n } from '@/i18n/provider';

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
};

const INSTALL_DISMISSED_KEY = 'shuku:pwa:install-dismissed';
const INSTALL_ACCEPTED_KEY = 'shuku:pwa:install-accepted';
const PWA_DEBUG_ENABLED_KEY = 'shuku:pwa:debug-enabled';
const NETWORK_RECHECK_INTERVAL_MS = 30_000;

type DebugLevel = 'log' | 'info' | 'warn' | 'warning' | 'error';
type DebugLog = {
  id: number;
  level: DebugLevel;
  time: string;
  source: string;
  message: string;
};
type ConsoleMethod = 'log' | 'info' | 'warn' | 'error';

function isStandaloneDisplay() {
  if (typeof window === 'undefined') return false;
  return window.matchMedia('(display-mode: standalone)').matches || ('standalone' in navigator && Boolean((navigator as Navigator & { standalone?: boolean }).standalone));
}

function isIosSafari() {
  if (typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent;
  const isIos = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const isSafari = /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS|OPiOS/.test(ua);
  return isIos && isSafari;
}

function canShowInstallHint() {
  if (typeof window === 'undefined') return false;
  if (isStandaloneDisplay()) return false;
  return localStorage.getItem(userDevicePreferenceKey(INSTALL_ACCEPTED_KEY)) !== '1'
    && localStorage.getItem(userDevicePreferenceKey(INSTALL_DISMISSED_KEY)) !== '1';
}

export async function clearPrivatePwaStorage() {
  window.dispatchEvent(new CustomEvent('shuku:private-data-clearing'));
  navigator.serviceWorker?.controller?.postMessage({ type: 'CLEAR_PRIVATE_CACHES' });
  deactivateReaderUser();
  clearCurrentUserNamespace();
  const runtime = getReaderRuntime();
  await Promise.all([clearPrivatePwaData(), clearPrivateReaderData(runtime.storage)]);
}

export function PwaClient() {
  const pathname = usePathname();
  const session = useAppSession();
  const [offline, setOffline] = useState(false);
  const [recentlyRestored, setRecentlyRestored] = useState(false);
  const [installEvent, setInstallEvent] = useState<BeforeInstallPromptEvent | null>(null);
  const [showIosHint, setShowIosHint] = useState(false);
  const [updateWorker, setUpdateWorker] = useState<ServiceWorker | null>(null);
  const [activatingUpdate, setActivatingUpdate] = useState(false);
  const [forcedUpdate, setForcedUpdate] = useState<{ phase: 'updating' | 'failed' } | null>(null);
  const refreshingRef = useRef(false);
  const forcedUpdateRef = useRef(false);
  const registrationRef = useRef<ServiceWorkerRegistration | null>(null);
  const latestVersionRef = useRef('');
  const restoreTimerRef = useRef<number | null>(null);
  const offlineRef = useRef(false);
  const installPromptAllowed = useMemo(
    () => !(
      pathname === '/login'
      || pathname === '/setup'
      || pathname === '/forgot-password'
      || pathname === '/reset-password'
      || pathname.startsWith('/reader/')
      || pathname.startsWith('/listen/')
    ),
    [pathname]
  );
  const showInstallPrompt = useMemo(
    () => installPromptAllowed && (Boolean(installEvent) || showIosHint),
    [installEvent, installPromptAllowed, showIosHint]
  );

  const performForcedUpdate = useCallback(async (registration: ServiceWorkerRegistration, latestVersion: string) => {
    if (forcedUpdateRef.current) return;
    forcedUpdateRef.current = true;
    latestVersionRef.current = latestVersion;
    setUpdateWorker(null);
    setForcedUpdate({ phase: 'updating' });
    try {
      const latestWorker = await waitForLatestWorker(registration, latestVersion);
      await prepareForPwaUpdate();
      await getReaderRuntime().progress.flushNow({ timeoutMs: 5_000 });
      refreshingRef.current = true;
      await purgeFrontendResourcesAndActivate(latestWorker);
      window.setTimeout(() => window.location.reload(), 5_000);
    } catch (reason) {
      refreshingRef.current = false;
      forcedUpdateRef.current = false;
      console.error('forced frontend resource update failed', reason);
      setForcedUpdate({ phase: 'failed' });
    }
  }, []);

  const checkForForcedUpdate = useCallback(async (registration: ServiceWorkerRegistration) => {
    if (forcedUpdateRef.current || !navigator.serviceWorker.controller) return;
    try {
      const { status } = await checkFrontendResourceVersion(
        navigator.serviceWorker.controller,
        withBasePath('/api/app-config')
      );
      if (status.updateRequired) await performForcedUpdate(registration, status.latestVersion);
    } catch {
      // A transient version-check failure must not break an otherwise usable offline client.
    }
  }, [performForcedUpdate]);

  useEffect(() => {
    const userId = session?.user?.id;
    if (!userId) return;
    const authzVersion = Number(session.authorization?.authzVersion ?? 1);
    activateReaderUser(userId);
    setCurrentUserNamespace(userId, authzVersion);
    navigator.serviceWorker?.controller?.postMessage({
      type: 'SET_PRIVATE_CACHE_NAMESPACE',
      userId,
      authzVersion
    });
  }, [session?.authorization?.authzVersion, session?.user?.id]);

  useEffect(() => {
    setShowIosHint(canShowInstallHint() && isIosSafari());
    let disposed = false;
    let networkCheckSequence = 0;

    async function updateOnlineState(checkForUpdate = false) {
      const sequence = ++networkCheckSequence;
      const applicationOnline = await resolveApplicationOnline(
        navigator.onLine,
        () => probeApplicationReachability(withBasePath('/api/app-config'))
      );
      if (disposed || sequence !== networkCheckSequence) return;

      const wasOffline = offlineRef.current;
      const nextOffline = !applicationOnline;
      offlineRef.current = nextOffline;
      setOffline(nextOffline);
      if (wasOffline && applicationOnline) {
        setRecentlyRestored(true);
        if (restoreTimerRef.current) window.clearTimeout(restoreTimerRef.current);
        restoreTimerRef.current = window.setTimeout(() => setRecentlyRestored(false), 4200);
      }
      if (applicationOnline && checkForUpdate && registrationRef.current) {
        void checkForForcedUpdate(registrationRef.current);
      }
    }

    function handleOnlineStateEvent() {
      void updateOnlineState(true);
    }

    function onBeforeInstallPrompt(event: Event) {
      if (!canShowInstallHint()) return;
      event.preventDefault();
      setShowIosHint(false);
      setInstallEvent(event as BeforeInstallPromptEvent);
    }

    function onAppInstalled() {
      localStorage.setItem(userDevicePreferenceKey(INSTALL_ACCEPTED_KEY), '1');
      setInstallEvent(null);
      setShowIosHint(false);
    }

    window.addEventListener('online', handleOnlineStateEvent);
    window.addEventListener('offline', handleOnlineStateEvent);
    window.addEventListener('beforeinstallprompt', onBeforeInstallPrompt);
    window.addEventListener('appinstalled', onAppInstalled);
    startReaderRuntime();
    void updateOnlineState();
    const networkRecheckTimer = window.setInterval(() => {
      if (!navigator.onLine) void updateOnlineState();
    }, NETWORK_RECHECK_INTERVAL_MS);

    const canRegisterServiceWorker = process.env.NODE_ENV === 'production' && 'serviceWorker' in navigator;
    if (canRegisterServiceWorker) {
      navigator.serviceWorker.register(withBasePath('/sw.js'), { updateViaCache: 'none' }).then((registration) => {
        registrationRef.current = registration;
        if (registration.waiting && navigator.serviceWorker.controller) {
          setUpdateWorker(registration.waiting);
        }
        registration.addEventListener('updatefound', () => {
          const nextWorker = registration.installing;
          if (!nextWorker) return;
          nextWorker.addEventListener('statechange', () => {
            if (nextWorker.state === 'installed' && navigator.serviceWorker.controller) {
              setUpdateWorker(nextWorker);
            }
          });
        });
        void checkForForcedUpdate(registration);
      }).catch(() => undefined);

      const handleControllerChange = () => {
        if (!refreshingRef.current) return;
        window.location.reload();
      };
      const handleVisibilityChange = () => {
        if (document.visibilityState === 'visible') void updateOnlineState(true);
      };
      navigator.serviceWorker.addEventListener('controllerchange', handleControllerChange);
      document.addEventListener('visibilitychange', handleVisibilityChange);
      const versionCheckTimer = window.setInterval(() => {
        if (registrationRef.current) void checkForForcedUpdate(registrationRef.current);
      }, 60_000);

      return () => {
        disposed = true;
        window.removeEventListener('online', handleOnlineStateEvent);
        window.removeEventListener('offline', handleOnlineStateEvent);
        window.removeEventListener('beforeinstallprompt', onBeforeInstallPrompt);
        window.removeEventListener('appinstalled', onAppInstalled);
        navigator.serviceWorker.removeEventListener('controllerchange', handleControllerChange);
        document.removeEventListener('visibilitychange', handleVisibilityChange);
        window.clearInterval(versionCheckTimer);
        window.clearInterval(networkRecheckTimer);
        if (restoreTimerRef.current) window.clearTimeout(restoreTimerRef.current);
        stopReaderRuntime();
      };
    }

    return () => {
      disposed = true;
      window.removeEventListener('online', handleOnlineStateEvent);
      window.removeEventListener('offline', handleOnlineStateEvent);
      window.removeEventListener('beforeinstallprompt', onBeforeInstallPrompt);
      window.removeEventListener('appinstalled', onAppInstalled);
      window.clearInterval(networkRecheckTimer);
      if (restoreTimerRef.current) window.clearTimeout(restoreTimerRef.current);
      stopReaderRuntime();
    };
  }, [checkForForcedUpdate]);

  async function installPwa() {
    if (!installEvent) return;
    await installEvent.prompt();
    const choice = await installEvent.userChoice.catch(() => null);
    if (choice?.outcome === 'accepted') {
      localStorage.setItem(userDevicePreferenceKey(INSTALL_ACCEPTED_KEY), '1');
    } else {
      localStorage.setItem(userDevicePreferenceKey(INSTALL_DISMISSED_KEY), '1');
    }
    setInstallEvent(null);
  }

  function dismissInstallPrompt() {
    localStorage.setItem(userDevicePreferenceKey(INSTALL_DISMISSED_KEY), '1');
    setInstallEvent(null);
    setShowIosHint(false);
  }

  async function activateUpdate() {
    if (!updateWorker || activatingUpdate) return;
    const worker = updateWorker;
    setActivatingUpdate(true);
    await prepareForPwaUpdate();
    refreshingRef.current = true;
    worker.postMessage({ type: 'SKIP_WAITING' });
  }

  return (
    <>
      <OfflineBanner offline={offline} recentlyRestored={recentlyRestored} />
      {showInstallPrompt ? (
        <InstallPwaPrompt
          androidInstallReady={Boolean(installEvent)}
          iosHint={showIosHint}
          onInstall={() => { void installPwa(); }}
          onDismiss={dismissInstallPrompt}
        />
      ) : null}
      {updateWorker ? <UpdateAvailableToast activating={activatingUpdate} onRefresh={() => { void activateUpdate(); }} /> : null}
      {forcedUpdate ? (
        <ForcedUpdateOverlay
          phase={forcedUpdate.phase}
          onRetry={() => {
            const registration = registrationRef.current;
            if (registration && latestVersionRef.current) void performForcedUpdate(registration, latestVersionRef.current);
          }}
        />
      ) : null}
      <PwaDebugPanel />
    </>
  );
}

function OfflineBanner({ offline, recentlyRestored }: { offline: boolean; recentlyRestored: boolean }) {
  const { t: i18nExpression } = useExpressionI18n();
  if (!offline && !recentlyRestored) return null;
  return (
    <div
      className={cn(
        'fixed inset-x-3 z-[80] mx-auto flex min-h-11 max-w-md items-center justify-center gap-2 rounded-2xl border px-4 py-2.5 text-center text-sm font-medium shadow-xl backdrop-blur',
        'shuku-pwa-bottom-overlay bottom-20 lg:bottom-6',
        offline
          ? 'border-amber-200 bg-amber-50/95 text-amber-900 shadow-amber-950/10'
          : 'border-emerald-200 bg-emerald-50/95 text-emerald-900 shadow-emerald-950/10'
      )}
      role="status"
      aria-live="polite"
    >
      {offline ? <WifiOff size={17} className="shrink-0" /> : <Wifi size={17} className="shrink-0" />}
      <span>{offline ? i18nExpression("当前网络不可用，尚未加载的读物与音频将无法打开。") : i18nExpression("网络已恢复，正在同步使用进度")}</span>
    </div>
  );
}

function InstallPwaPrompt({ androidInstallReady, iosHint, onInstall, onDismiss }: { androidInstallReady: boolean; iosHint: boolean; onInstall: () => void; onDismiss: () => void }) {
  const { t: i18nAttribute } = useAttributeI18n();
  return (
    <div className="shuku-pwa-bottom-overlay fixed inset-x-3 bottom-20 z-[70] mx-auto max-w-md rounded-2xl border border-slate-200 bg-white/95 p-4 text-slate-900 shadow-2xl shadow-slate-950/15 backdrop-blur lg:bottom-6">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 gap-3">
          <div className="h-10 w-10 shrink-0 overflow-hidden rounded-xl bg-[#F7F1E8] shadow-sm">
            <Image src={withBasePath('/icons/icon-192.png')} alt="" width={40} height={40} className="h-full w-full object-cover" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold"><I18nText>添加到桌面</I18nText></div>
            <div className="mt-1 text-xs leading-5 text-slate-600">
              {iosHint ? i18nAttribute("点击分享按钮 → 添加到主屏幕") : i18nAttribute("把{value0}添加到桌面，获得更接近 App 的阅读体验。", { value0: PRODUCT_NAME })}
            </div>
          </div>
        </div>
        <button type="button" onClick={onDismiss} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-slate-500 transition hover:bg-slate-100" aria-label={i18nAttribute("关闭安装提示")}>
          <X size={17} />
        </button>
      </div>
      {androidInstallReady ? (
        <button type="button" onClick={onInstall} className="mt-3 flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-slate-950 px-4 text-sm font-medium text-white transition active:scale-[0.99] hover:bg-slate-800">
          <Download size={17} />
          <I18nText>添加到桌面</I18nText></button>
      ) : null}
    </div>
  );
}

function UpdateAvailableToast({ activating, onRefresh }: { activating: boolean; onRefresh: () => void }) {
  const { t: i18nExpression } = useExpressionI18n();
  return (
    <div className="shuku-pwa-top-overlay fixed inset-x-3 top-4 z-[90] mx-auto max-w-md rounded-2xl border border-blue-200 bg-blue-50/95 p-4 text-blue-950 shadow-2xl shadow-blue-950/10 backdrop-blur" role="status" aria-live="polite">
      <div className="text-sm font-semibold"><I18nText>发现新版本</I18nText></div>
      <p className="mt-1 text-xs leading-5 text-blue-900"><I18nText>请在合适的阅读位置确认升级；应用不会自动刷新正在阅读的页面。</I18nText></p>
      <button type="button" disabled={activating} onClick={onRefresh} className="mt-3 flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-medium text-white transition active:scale-[0.99] hover:bg-blue-700 disabled:cursor-wait disabled:opacity-70">
        <RefreshCw size={17} className={activating ? 'animate-spin motion-reduce:animate-none' : undefined} />
        {activating ? i18nExpression("正在保存当前位置…") : i18nExpression("保存当前位置并升级")}
      </button>
    </div>
  );
}

function ForcedUpdateOverlay({ phase, onRetry }: { phase: 'updating' | 'failed'; onRetry: () => void }) {
  const { t: i18nExpression } = useExpressionI18n();
  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm" role="alertdialog" aria-modal="true" aria-labelledby="forced-update-title" aria-describedby="forced-update-description">
      <div className="w-full max-w-md rounded-3xl border border-blue-200 bg-white p-6 text-slate-900 shadow-2xl">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-blue-50 text-blue-700">
            <RefreshCw size={21} className={phase === 'updating' ? 'animate-spin motion-reduce:animate-none' : undefined} />
          </span>
          <h2 id="forced-update-title" className="text-base font-semibold">
            {phase === 'updating' ? i18nExpression("检测到必须安装的前端资源更新") : i18nExpression("前端资源更新失败")}
          </h2>
        </div>
        <p id="forced-update-description" className="mt-4 text-sm leading-6 text-slate-600">
          {phase === 'updating' ? i18nExpression("正在保存当前位置并安装最新版，请勿关闭应用。") : i18nExpression("应用必须完成更新后才能继续使用。")}
        </p>
        {phase === 'failed' ? (
          <button type="button" onClick={onRetry} className="mt-5 flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 active:scale-[0.99]">
            <RefreshCw size={17} />
            <I18nText>重试更新</I18nText>
          </button>
        ) : null}
      </div>
    </div>
  );
}

function shouldEnablePwaDebug() {
  if (typeof window === 'undefined') return false;
  const params = new URLSearchParams(window.location.search);
  const requested = params.get('debug') ?? params.get('pwaDebug');
  if (requested === '1' || requested === 'true') {
    localStorage.setItem(userDevicePreferenceKey(PWA_DEBUG_ENABLED_KEY), '1');
    return true;
  }
  if (requested === '0' || requested === 'false') {
    localStorage.removeItem(userDevicePreferenceKey(PWA_DEBUG_ENABLED_KEY));
    return false;
  }
  return localStorage.getItem(userDevicePreferenceKey(PWA_DEBUG_ENABLED_KEY)) === '1';
}

function stringifyDebugValue(value: unknown) {
  if (value instanceof Error) return value.stack || value.message;
  if (typeof value === 'string') return value;
  if (typeof value === 'undefined') return 'undefined';
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function getStandaloneLabel() {
  if (typeof window === 'undefined') return 'unknown';
  if (isStandaloneDisplay()) return 'standalone';
  if (window.matchMedia('(display-mode: browser)').matches) return 'browser';
  return 'unknown';
}

function PwaDebugPanel() {
  const { t: i18nAttribute, locale } = useAttributeI18n();
  const [enabled, setEnabled] = useState(false);
  const [collapsed, setCollapsed] = useState(true);
  const [copied, setCopied] = useState(false);
  const [logs, setLogs] = useState<DebugLog[]>([]);
  const nextIdRef = useRef(1);

  const appendLog = useCallback((level: DebugLevel, source: string, parts: unknown[]) => {
    const entry: DebugLog = {
      id: nextIdRef.current,
      level,
      source,
      time: new Date().toLocaleTimeString(locale, { hour12: false }),
      message: parts.map(stringifyDebugValue).join(' ')
    };
    nextIdRef.current += 1;
    setLogs((current) => [...current.slice(-119), entry]);
  }, [locale]);

  useEffect(() => {
    setEnabled(shouldEnablePwaDebug());
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;

    const methods: ConsoleMethod[] = ['log', 'info', 'warn', 'error'];
    const originals = new Map<ConsoleMethod, typeof console.log>();
    methods.forEach((method) => {
      const original = console[method];
      originals.set(method, original);
      console[method] = (...args: unknown[]) => {
        original.apply(console, args);
        appendLog(method, 'console', args);
      };
    });

    function recordOnlineState() {
      appendLog(navigator.onLine ? 'info' : 'warn', 'network', [navigator.onLine ? 'online' : 'offline']);
    }

    function recordVisibility() {
      appendLog('info', 'page', [`visibility=${document.visibilityState}`]);
    }

    function recordError(event: ErrorEvent) {
      appendLog('error', 'window', [event.message, event.filename ? `${event.filename}:${event.lineno}:${event.colno}` : '']);
    }

    function recordUnhandledRejection(event: PromiseRejectionEvent) {
      appendLog('error', 'promise', [event.reason]);
    }

    function recordServiceWorkerMessage(event: MessageEvent) {
      if (event.data?.type !== 'PWA_DEBUG_LOG') return;
      const payload = event.data.payload as { level?: DebugLevel; source?: string; message?: string; details?: unknown };
      appendLog(payload.level ?? 'info', payload.source ?? 'service-worker', [payload.message, payload.details].filter(Boolean));
    }

    function recordControllerChange() {
      appendLog('info', 'service-worker', ['controllerchange']);
    }

    function recordReaderDebug(event: Event) {
      const detail = (event as CustomEvent<{ level?: DebugLevel; message?: string; data?: unknown }>).detail;
      if (!detail) return;
      appendLog(detail.level ?? 'info', 'reader-v4', [detail.message ?? 'event', detail.data].filter((item) => typeof item !== 'undefined'));
    }

    appendLog('info', 'pwa', [
      `mode=${getStandaloneLabel()}`,
      `online=${navigator.onLine}`,
      `secure=${window.isSecureContext}`,
      `sw=${'serviceWorker' in navigator ? 'supported' : 'unsupported'}`
    ]);

    const readerRuntime = getReaderRuntime();
    void readerRuntime.storage.listDiagnostics(30).then((diagnostics) => {
      appendLog('info', 'reader-v4/snapshot', [`diagnostics=${diagnostics.length}`]);
      diagnostics.reverse().forEach((item) => appendLog(item.level === 'warning' ? 'warn' : item.level, `reader-v4/${item.code}`, [item.message, item.data]));
    }).catch((error) => appendLog('warn', 'reader-v4/snapshot', ['读取本地诊断失败', error]));

    navigator.serviceWorker?.getRegistration().then((registration) => {
      appendLog('info', 'service-worker', [
        registration
          ? `scope=${registration.scope} active=${registration.active?.state ?? 'none'} waiting=${registration.waiting?.state ?? 'none'}`
          : 'not registered'
      ]);
    }).catch((error) => appendLog('warn', 'service-worker', ['registration lookup failed', error]));

    window.addEventListener('online', recordOnlineState);
    window.addEventListener('offline', recordOnlineState);
    document.addEventListener('visibilitychange', recordVisibility);
    window.addEventListener('error', recordError);
    window.addEventListener('unhandledrejection', recordUnhandledRejection);
    navigator.serviceWorker?.addEventListener('message', recordServiceWorkerMessage);
    navigator.serviceWorker?.addEventListener('controllerchange', recordControllerChange);
    window.addEventListener('shuku:reader-debug', recordReaderDebug);

    return () => {
      methods.forEach((method) => {
        const original = originals.get(method);
        if (original) console[method] = original;
      });
      window.removeEventListener('online', recordOnlineState);
      window.removeEventListener('offline', recordOnlineState);
      document.removeEventListener('visibilitychange', recordVisibility);
      window.removeEventListener('error', recordError);
      window.removeEventListener('unhandledrejection', recordUnhandledRejection);
      navigator.serviceWorker?.removeEventListener('message', recordServiceWorkerMessage);
      navigator.serviceWorker?.removeEventListener('controllerchange', recordControllerChange);
      window.removeEventListener('shuku:reader-debug', recordReaderDebug);
    };
  }, [appendLog, enabled]);

  function disableDebug() {
    localStorage.removeItem(userDevicePreferenceKey(PWA_DEBUG_ENABLED_KEY));
    setEnabled(false);
  }

  async function copyLogs() {
    const text = logs.map((log) => `[${log.time}] ${log.source}/${log.level}: ${log.message}`).join('\n');
    await navigator.clipboard?.writeText(text).catch(() => undefined);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  if (!enabled) return null;

  return (
    <div className="shuku-pwa-bottom-overlay fixed inset-x-2 bottom-20 z-[120] mx-auto max-w-xl text-slate-50 lg:bottom-3">
      {collapsed ? (
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          className="ml-auto flex min-h-11 items-center gap-2 rounded-full border border-slate-700 bg-slate-950/95 px-4 text-xs font-medium shadow-2xl shadow-slate-950/25 backdrop-blur"
          aria-label={i18nAttribute("打开 PWA 调试面板")}
        >
          <Bug size={16} />
          PWA Debug
        </button>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-slate-700 bg-slate-950/95 shadow-2xl shadow-slate-950/30 backdrop-blur">
          <div className="flex min-h-12 items-center justify-between gap-3 border-b border-slate-800 px-3">
            <div className="flex items-center gap-2 text-xs font-semibold">
              <Bug size={15} />
              PWA Debug
            </div>
            <div className="flex items-center gap-1">
              <button type="button" onClick={() => { void copyLogs(); }} className="flex h-9 w-9 items-center justify-center rounded-full text-slate-300 transition hover:bg-slate-800" aria-label={i18nAttribute("复制日志")}>
                <Clipboard size={15} />
              </button>
              <button type="button" onClick={() => setLogs([])} className="flex h-9 w-9 items-center justify-center rounded-full text-slate-300 transition hover:bg-slate-800" aria-label={i18nAttribute("清空日志")}>
                <Trash2 size={15} />
              </button>
              <button type="button" onClick={() => setCollapsed(true)} className="flex h-9 w-9 items-center justify-center rounded-full text-slate-300 transition hover:bg-slate-800" aria-label={i18nAttribute("收起调试面板")}>
                <X size={15} />
              </button>
            </div>
          </div>
          {copied ? <div className="border-b border-emerald-900/60 bg-emerald-950 px-3 py-2 text-xs text-emerald-100"><I18nText>日志已复制</I18nText></div> : null}
          <div className="max-h-72 overflow-y-auto px-3 py-2 font-mono text-[11px] leading-5" data-pwa-scroll="true">
            {logs.length ? logs.map((log) => (
              <div key={log.id} className={cn('break-words border-b border-slate-900 py-1 last:border-0', log.level === 'error' ? 'text-rose-200' : log.level === 'warn' || log.level === 'warning' ? 'text-amber-200' : 'text-slate-200')}>
                <span className="text-slate-500">{log.time}</span>
                <span className="ml-2 text-slate-400">{log.source}/{log.level}</span>
                <span className="ml-2">{log.message}</span>
              </div>
            )) : <div className="py-5 text-center text-slate-500"><I18nText>暂无日志</I18nText></div>}
          </div>
          <div className="flex items-center justify-between gap-2 border-t border-slate-800 px-3 py-2 text-[11px] text-slate-400">
            <span><I18nText>URL 加 ?debug=0 可关闭持久开关</I18nText></span>
            <button type="button" onClick={disableDebug} className="rounded-full px-3 py-1.5 text-slate-300 transition hover:bg-slate-800"><I18nText>关闭</I18nText></button>
          </div>
        </div>
      )}
    </div>
  );
}

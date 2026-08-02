'use client';

import type { ReaderCapabilities, ReaderKind, ReaderPreferences } from '@shuku/reader-core';
import { Bookmark, Check, ChevronLeft, ChevronRight, Gauge, Highlighter, ListTree, Minus, Plus, RotateCcw, Rows2, Rows3, Rows4, Settings, Trash2, X, type LucideIcon } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type ReactNode, type SyntheticEvent } from 'react';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { VolumeSelect } from '../../components/ui/volume-select';
import { useI18n } from '../../i18n/provider';
import { isDarkReaderTheme, readerThemeSurfaces } from './reader-theme';
import {
  READER_COMIC_DIRECTION_OPTIONS,
  READER_COMIC_IMAGE_FIT_OPTIONS,
  READER_COMIC_IMAGE_VARIANT_OPTIONS,
  READER_FLOW_OPTIONS,
  READER_FONT_FAMILY_OPTIONS,
  READER_FONT_SIZE_OPTIONS,
  READER_LINE_HEIGHT_OPTIONS,
  READER_PAGE_TURN_ANIMATION_OPTIONS,
  READER_PAGE_WIDTH_OPTIONS,
  READER_PDF_FIT_OPTIONS,
  READER_SPREAD_MODE_OPTIONS,
  READER_THEME_OPTIONS,
  closestReaderOptionValue,
  type ReaderFontFamily
} from './reader-preference-options';
import type { ReaderBookmark } from './v3/bookmarks';
import { resolveActiveEpubNavigationIndex } from './v3/epub-navigation';
import type { ReaderInteractionPolicy } from './v3/adapters/reader-interaction';
import { hasActiveTextSelection, isReaderControlTarget, readerKeyIntent, readerPinchZoom, readerPointerIntentInViewport, readerSwipeIntent, type ReaderInputIntent } from './v3/input-router';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type ComicDirection = ReaderPreferences['comic']['direction'];
type ComicMode = ReaderPreferences['comic']['mode'];
type ComicPageTurnAnimation = ReaderPreferences['comic']['pageTurnAnimation'];
type ComicImageFit = ReaderPreferences['comic']['imageFit'];
type ComicImageVariant = ReaderPreferences['comic']['imageVariant'];

export type ReaderTheme = ReaderPreferences['appearance']['theme'];
export const readerFontFamilyOptions = READER_FONT_FAMILY_OPTIONS;
const readerFontSizeOptions = READER_FONT_SIZE_OPTIONS;
const readerLineHeightOptions = READER_LINE_HEIGHT_OPTIONS.map((option, index) => ({
  ...option,
  icon: [Rows2, Rows3, Rows4][index]
}));
export type { ReaderFontFamily };
export type EbookPageTurnAnimation = ReaderPreferences['epub']['pageTurnAnimation'];
export type EbookSpreadMode = ReaderPreferences['epub']['spreadMode'];
export type EbookFlow = 'paginated' | 'scrolled';
export type PdfFit = 'width' | 'page';

export type ReaderProgress = {
  page: number;
  total: number | null;
  percent: number;
  position: string;
  label: string;
};

export type ReaderControls = {
  next: () => Promise<void>;
  prev: () => Promise<void>;
  jumpToProgress: (value: number) => Promise<void>;
  jumpToHref?: (href: string) => Promise<void>;
  jumpToIndex?: (index: number) => Promise<void>;
};

export type ReaderSettings = {
  theme: ReaderTheme;
  fontSize: number;
  lineHeight: number;
  pageWidth: number;
  fontFamily: ReaderFontFamily;
  ebookPageTurnAnimation: EbookPageTurnAnimation;
  ebookSpreadMode: EbookSpreadMode;
  ebookFlow: EbookFlow;
  comicZoom: number;
  pdfZoom: number;
  comicDirection: ComicDirection;
  comicMode: ComicMode;
  comicPageTurnAnimation: ComicPageTurnAnimation;
  imageFit: ComicImageFit;
  imageVariant: ComicImageVariant;
  pdfFit: PdfFit;
};

export type ReaderShellEvents = {
  enterImmersive: () => void;
  toggleControls: () => void;
  escape: () => void;
  shouldIgnoreInteraction: (target: EventTarget | null) => boolean;
  isInteractionBlocked: () => boolean;
};

type ReaderShellProps = {
  readerType: ReaderKind;
  progress: ReaderProgress;
  progressExtra?: Record<string, unknown>;
  controls: ReaderControls | null;
  settings: ReaderSettings;
  capabilities?: ReaderCapabilities | null;
  readingDirection?: ComicDirection;
  onBack: () => void;
  onSettingsChange: (settings: ReaderSettings) => void;
  onResetSettings?: () => void | Promise<void>;
  interactionBlocked?: boolean;
  horizontalPaging?: ReaderInteractionPolicy['horizontalPaging'];
  navigationItems?: ReaderNavigationItem[];
  volumeNavigation?: ReaderVolumeNavigation;
  bookmarkActive?: boolean;
  currentBookmarkId?: string | null;
  bookmarks?: ReaderBookmark[];
  canBookmark?: boolean;
  onToggleBookmark?: () => void;
  onJumpBookmark?: (bookmark: ReaderBookmark) => void | Promise<void>;
  onRemoveBookmark?: (id: string) => void;
  children: ReactNode | ((events: ReaderShellEvents) => ReactNode);
};

export type ReaderNavigationItem = {
  index: number;
  title: string;
  href?: string;
  navigationKey?: string;
  sectionIndex?: number;
};

export type ReaderVolumeNavigation = {
  volumeSections: Array<{ id: string; title: string; pageCount: number }>;
  pages: ReaderNavigationItem[];
  currentVolumeId: string;
  loading: boolean;
  onSelectVolume: (volumeId: string) => void;
  onSelectItem: (item: ReaderNavigationItem) => void;
};

const readerBottomAreaHeight = 'calc(5.75rem + var(--shuku-safe-area-bottom))';
const readerBottomControlsMaxWidth = 'max-w-5xl';
const progressJumpDebounceMs = 160;
type ReaderPanel = 'toc' | 'bookmarks' | 'settings' | 'annotations' | 'progress';
type ReaderPanelPlacement = { left: number; bottom: number };

function clampPercent(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function progressPageLabel(progress: ReaderProgress) {
  return progress.total ? `第 ${progress.page} 页 / 共 ${progress.total} 页` : `第 ${progress.page} 页`;
}

function bookmarkDateLabel(createdAt: string, locale: string) {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(locale, { month: 'numeric', day: 'numeric' }).format(date);
}

function numberFromExtra(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function navigationItemKey(item: ReaderNavigationItem) {
  return `${item.index}:${item.href ?? ''}:${item.title}`;
}

function activeNavigationItem(readerType: ReaderKind, items: ReaderNavigationItem[], progress: ReaderProgress, progressExtra: Record<string, unknown>) {
  if (readerType !== 'reflowable') return items.find((item) => item.index === progress.page) ?? null;
  const navigationKey = typeof progressExtra.navigationKey === 'string'
    ? progressExtra.navigationKey
    : null;
  if (navigationKey) {
    return items.find((item) => item.navigationKey === navigationKey) ?? null;
  }
  const href = progressExtra.currentHref ?? progressExtra.chapterHref;
  const index = resolveActiveEpubNavigationIndex(items, href, null);
  return index === null ? null : items[index] ?? null;
}

function precisePercent(value: number, readerType: ReaderKind, locale: string) {
  const safe = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: readerType === 'reflowable' ? 1 : 0,
    maximumFractionDigits: readerType === 'reflowable' ? 1 : 0
  }).format(safe);
}

function foliateLocationLabel(extra: Record<string, unknown>) {
  const current = numberFromExtra(extra.locationCurrent);
  const next = numberFromExtra(extra.locationNext);
  const total = numberFromExtra(extra.locationTotal);
  if (current === null || next === null || total === null || total < 1) return null;
  const start = Math.min(total, Math.floor(current) + 1);
  const end = Math.min(total, Math.max(start, Math.floor(next) + 1));
  return start === end ? `Loc ${start} / ${total}` : `Loc ${start}–${end} / ${total}`;
}

function remainingMinutesLabel(seconds: number | null, translate: (source: string, values?: Record<string, string | number>) => string) {
  if (seconds === null) return null;
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  return translate('预计 {value0} 分钟', { value0: minutes });
}

function stopControlEvent(event: MouseEvent) {
  event.stopPropagation();
}

function inertWhen(condition: boolean): { inert?: boolean } {
  return condition ? { inert: true } : {};
}

function shouldIgnoreReaderInteraction(target: EventTarget | null) {
  return isReaderControlTarget(target) || hasActiveTextSelection(window.getSelection());
}

export function ReaderShell({ readerType, progress, progressExtra = {}, controls, settings, capabilities = null, readingDirection, onBack, onSettingsChange, onResetSettings, interactionBlocked = false, horizontalPaging = 'shell-discrete', navigationItems, volumeNavigation, bookmarkActive = false, currentBookmarkId = null, bookmarks = [], canBookmark = false, onToggleBookmark, onJumpBookmark, onRemoveBookmark, children }: ReaderShellProps) {
  const { t: i18nAttribute } = useAttributeI18n();
  const { locale } = useI18n();
  const controlsVisibleRef = useRef(false);
  const controlsRef = useRef<ReaderControls | null>(null);
  const readerViewportRef = useRef<HTMLElement | null>(null);
  const panelRef = useRef<ReaderPanel | null>(null);
  const touchRef = useRef({ x: 0, y: 0, time: 0, singleTouch: false });
  const pinchRef = useRef({ active: false, startDistance: 0, startZoom: 1, nextZoom: 1 });
  const suppressClickUntilRef = useRef(0);
  const backRequestAtRef = useRef(0);
  const progressJumpTimerRef = useRef<number | null>(null);
  const pendingProgressJumpRef = useRef<number | null>(null);
  const readerDirectionRef = useRef<ComicDirection>('ltr');
  const interactionBlockedRef = useRef(interactionBlocked);
  const capabilitiesRef = useRef<ReaderCapabilities | null>(capabilities);
  const handleInputIntentRef = useRef<(intent: ReaderInputIntent | null) => void>(() => undefined);
  const panelElementRef = useRef<HTMLElement | null>(null);
  const panelReturnFocusRef = useRef<HTMLElement | null>(null);
  const [controlsVisible, setControlsVisible] = useState(false);
  const [panel, setPanel] = useState<ReaderPanel | null>(null);
  const [panelPlacement, setPanelPlacement] = useState<ReaderPanelPlacement | null>(null);
  const [annotationTab, setAnnotationTab] = useState<'book' | 'mine'>('book');
  const [bookmarkNotice, setBookmarkNotice] = useState('');
  const navItems = navigationItems ?? [];
  const orderedBookmarks = [...bookmarks].sort((left, right) => left.percent - right.percent || left.createdAt.localeCompare(right.createdAt));
  const [progressScrubPercent, setProgressScrubPercent] = useState<number | null>(null);
  const dark = isDarkReaderTheme(settings.theme);
  const themeSurface = readerThemeSurfaces[settings.theme];
  const currentNavigationItem = activeNavigationItem(readerType, navItems, progress, progressExtra);
  const currentNavigationTitle = currentNavigationItem?.title ?? null;
  const currentNavigationLabel = currentNavigationTitle;
  const locationLabel = readerType === 'reflowable' ? foliateLocationLabel(progressExtra) : null;
  const sectionRemaining = remainingMinutesLabel(numberFromExtra(progressExtra.remainingSectionSeconds), i18nAttribute);
  const totalRemaining = remainingMinutesLabel(numberFromExtra(progressExtra.remainingTotalSeconds), i18nAttribute);
  const progressDetail = [currentNavigationLabel, locationLabel, `${precisePercent(progress.percent, readerType, locale)}%`].filter(Boolean).join(' · ');
  const readerDirection: ComicDirection = readingDirection ?? (readerType === 'comic' ? settings.comicDirection : 'ltr');
  const zoomedPannable = readerType === 'pdf'
    ? settings.pdfZoom > 1
    : readerType === 'comic' && settings.comicZoom > 1;
  const usesCompactPassiveProgress = readerType === 'reflowable' || readerType === 'comic';
  const passiveProgressAreaHeight = usesCompactPassiveProgress ? 'calc(2.75rem + var(--shuku-safe-area-bottom))' : readerBottomAreaHeight;
  const supportsTextAnnotations = readerType !== 'comic';
  const accentColor = dark ? '#f59e0b' : '#b45309';
  panelRef.current = panel;
  interactionBlockedRef.current = interactionBlocked;
  capabilitiesRef.current = capabilities;

  function isInteractionBlocked() {
    return interactionBlockedRef.current || panelRef.current !== null;
  }

  function setControlsVisibility(visible: boolean) {
    controlsVisibleRef.current = visible;
    setControlsVisible(visible);
  }

  function keepControlsOpen() {
    setControlsVisibility(true);
  }

  function enterImmersive() {
    setControlsVisibility(false);
    setPanel(null);
  }

  function closePanel() {
    setPanel(null);
    window.requestAnimationFrame(() => panelReturnFocusRef.current?.focus());
  }

  function dismissPanelWithoutFocusRestore() {
    if (!panelRef.current) return;
    setPanel(null);
  }

  function togglePanel(next: ReaderPanel, returnFocus: HTMLElement) {
    panelReturnFocusRef.current = returnFocus;
    if (panelRef.current === next) closePanel();
    else setPanel(next);
  }

  function toggleBookmark(dismissPanel = true) {
    if (!canBookmark || !onToggleBookmark) return;
    if (dismissPanel) dismissPanelWithoutFocusRestore();
    onToggleBookmark();
    setBookmarkNotice(bookmarkActive ? '已移除当前书签' : '已添加当前书签');
    keepControlsOpen();
  }

  async function jumpToBookmark(bookmark: ReaderBookmark) {
    if (!onJumpBookmark) return;
    await onJumpBookmark(bookmark);
    closePanel();
    keepControlsOpen();
  }

  function toggleControls() {
    if (controlsVisibleRef.current) enterImmersive();
    else keepControlsOpen();
  }

  function closePanelOrImmersive() {
    if (panelRef.current) {
      closePanel();
      return;
    }
    enterImmersive();
  }

  function requestBackFromControl(event: SyntheticEvent) {
    event.preventDefault();
    event.stopPropagation();
    const now = Date.now();
    if (now - backRequestAtRef.current < 700) return;
    backRequestAtRef.current = now;
    onBack();
  }

  async function goNext() {
    if (capabilitiesRef.current?.canGoNext === false) return;
    await controlsRef.current?.next();
  }

  async function goPrev() {
    if (capabilitiesRef.current?.canGoPrevious === false) return;
    await controlsRef.current?.prev();
  }

  function goByIntent(intent: 'previous' | 'next') {
    if (intent === 'next') void goNext();
    else void goPrev();
  }

  async function jumpToStart() {
    if (capabilitiesRef.current?.canJumpToProgress === false) return;
    await controlsRef.current?.jumpToProgress(0);
  }

  async function jumpToEnd() {
    if (capabilitiesRef.current?.canJumpToProgress === false) return;
    await controlsRef.current?.jumpToProgress(100);
  }

  function clearPendingProgressJump() {
    if (progressJumpTimerRef.current !== null) {
      window.clearTimeout(progressJumpTimerRef.current);
      progressJumpTimerRef.current = null;
    }
    pendingProgressJumpRef.current = null;
  }

  function flushPendingProgressJump() {
    const value = pendingProgressJumpRef.current;
    clearPendingProgressJump();
    if (value === null) return;
    void controlsRef.current?.jumpToProgress(value);
  }

  function handleInputIntent(intent: ReaderInputIntent | null) {
    if (!intent) return;
    if (intent === 'escape') {
      if (panelRef.current) closePanelOrImmersive();
      else if (!interactionBlockedRef.current) enterImmersive();
    }
    else if (isInteractionBlocked()) return;
    else if (intent === 'toggle-controls') toggleControls();
    else if (intent === 'first') void jumpToStart();
    else if (intent === 'last') void jumpToEnd();
    else goByIntent(intent);
  }
  handleInputIntentRef.current = handleInputIntent;

  function handleReaderTap(clientX: number, clientY: number) {
    const bounds = readerViewportRef.current?.getBoundingClientRect();
    if (!bounds) return;
    handleInputIntent(readerPointerIntentInViewport(clientX, clientY, bounds, readerDirectionRef.current));
  }

  useEffect(() => {
    controlsRef.current = controls;
  }, [controls]);

  useEffect(() => {
    controlsVisibleRef.current = controlsVisible;
  }, [controlsVisible]);

  useEffect(() => {
    panelRef.current = panel;
  }, [panel]);

  useEffect(() => {
    readerDirectionRef.current = readerDirection;
  }, [readerDirection]);

  useEffect(() => {
    return () => clearPendingProgressJump();
  }, []);

  useEffect(() => {
    if (progressScrubPercent === null) return;
    if (Math.abs(clampPercent(progress.percent) - progressScrubPercent) <= 1) {
      setProgressScrubPercent(null);
    }
  }, [progress.percent, progressScrubPercent]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const intent = readerKeyIntent(event, readerDirectionRef.current);
      if (!intent) return;
      if (intent === 'escape') {
        event.preventDefault();
        handleInputIntentRef.current(intent);
        return;
      }
      if (isInteractionBlocked() || shouldIgnoreReaderInteraction(event.target)) return;
      event.preventDefault();
      handleInputIntentRef.current(intent);
    }

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (!panel) return;
    setControlsVisibility(true);
  }, [panel]);

  useLayoutEffect(() => {
    if (!panel) {
      setPanelPlacement(null);
      return undefined;
    }

    const updatePlacement = () => {
      const dialog = panelElementRef.current;
      const anchor = panelReturnFocusRef.current;
      if (!dialog || !anchor || !window.matchMedia('(min-width: 768px)').matches) {
        setPanelPlacement(null);
        return;
      }

      const anchorBounds = anchor.getBoundingClientRect();
      const dialogBounds = dialog.getBoundingClientRect();
      const horizontalInset = 20;
      const idealLeft = anchorBounds.left + (anchorBounds.width / 2) - (dialogBounds.width / 2);
      const left = Math.max(horizontalInset, Math.min(idealLeft, window.innerWidth - dialogBounds.width - horizontalInset));
      const bottom = Math.max(0, window.innerHeight - anchorBounds.top + 12);
      setPanelPlacement((current) => (
        current && Math.abs(current.left - left) < 0.5 && Math.abs(current.bottom - bottom) < 0.5
          ? current
          : { left, bottom }
      ));
    };

    updatePlacement();
    const frame = window.requestAnimationFrame(updatePlacement);
    const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(updatePlacement);
    if (panelElementRef.current) resizeObserver?.observe(panelElementRef.current);
    window.addEventListener('resize', updatePlacement);
    window.visualViewport?.addEventListener('resize', updatePlacement);
    return () => {
      window.cancelAnimationFrame(frame);
      resizeObserver?.disconnect();
      window.removeEventListener('resize', updatePlacement);
      window.visualViewport?.removeEventListener('resize', updatePlacement);
    };
  }, [panel]);

  useEffect(() => {
    if (!bookmarkNotice) return undefined;
    const timer = window.setTimeout(() => setBookmarkNotice(''), 1800);
    return () => window.clearTimeout(timer);
  }, [bookmarkNotice]);

  useEffect(() => {
    const dialog = panelElementRef.current;
    if (!panel || !dialog) return undefined;
    const focusableSelector = 'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';
    const focusables = () => Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector)).filter((element) => !element.hidden);
    window.requestAnimationFrame(() => focusables()[0]?.focus());
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const items = focusables();
      if (!items.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    dialog.addEventListener('keydown', trapFocus);
    return () => dialog.removeEventListener('keydown', trapFocus);
  }, [panel]);

  async function jumpToPercent(value: number, debounce = false) {
    if (capabilitiesRef.current?.canJumpToProgress === false) return;
    const nextValue = clampPercent(value);
    if (!debounce) {
      clearPendingProgressJump();
      setProgressScrubPercent(null);
      await controlsRef.current?.jumpToProgress(nextValue);
      return;
    }
    pendingProgressJumpRef.current = nextValue;
    setProgressScrubPercent(nextValue);
    if (progressJumpTimerRef.current !== null) {
      window.clearTimeout(progressJumpTimerRef.current);
    }
    progressJumpTimerRef.current = window.setTimeout(flushPendingProgressJump, progressJumpDebounceMs);
  }

  async function jumpToItem(item: ReaderNavigationItem) {
    if (item.href && capabilitiesRef.current?.canJumpToHref !== false && controls?.jumpToHref) {
      await controls.jumpToHref(item.href);
      closePanel();
      keepControlsOpen();
      return;
    }
    if (capabilitiesRef.current?.canJumpToIndex !== false && controls?.jumpToIndex) {
      await controls.jumpToIndex(item.index);
      closePanel();
      keepControlsOpen();
      return;
    }
    const total = progress.total ?? navItems.length;
    const percent = total > 1 ? ((item.index - 1) / (total - 1)) * 100 : 0;
    await jumpToPercent(percent);
    closePanel();
    keepControlsOpen();
  }

  function updateSettings(next: Partial<ReaderSettings>) {
    onSettingsChange({ ...settings, ...next });
    keepControlsOpen();
  }

  return (
    <div
      className={cn('fixed inset-0 z-50 min-h-0 overflow-clip transition-colors', themeSurface.textClass)}
      data-reader-shell="v3"
      data-reader-theme={settings.theme}
      data-reader-kind={readerType}
      data-reader-horizontal-paging={horizontalPaging}
      style={{
        backgroundColor: themeSurface.background
      }}
    >
      <div
        className="relative flex h-full min-h-0 flex-col overflow-clip"
        style={{
          backgroundColor: themeSurface.background,
          paddingTop: 'var(--shuku-safe-area-top)',
          paddingLeft: 'var(--shuku-safe-area-left)',
          paddingRight: 'var(--shuku-safe-area-right)'
        }}
      onClick={(event) => {
        if (isInteractionBlocked() || Date.now() < suppressClickUntilRef.current || shouldIgnoreReaderInteraction(event.target)) return;
        handleReaderTap(event.clientX, event.clientY);
      }}
      onTouchStart={(event) => {
        if (isInteractionBlocked() || shouldIgnoreReaderInteraction(event.target)) return;
        if (readerType === 'pdf' && event.touches.length === 2) {
          touchRef.current.singleTouch = false;
          const [first, second] = [event.touches[0], event.touches[1]];
          pinchRef.current = {
            active: true,
            startDistance: Math.hypot(second.clientX - first.clientX, second.clientY - first.clientY),
            startZoom: settings.pdfZoom,
            nextZoom: settings.pdfZoom
          };
          return;
        }
        if (event.touches.length !== 1) {
          touchRef.current.singleTouch = false;
          return;
        }
        const touch = event.changedTouches[0];
        if (!touch) return;
        touchRef.current = { x: touch.clientX, y: touch.clientY, time: Date.now(), singleTouch: true };
      }}
      onTouchMove={(event) => {
        if (event.touches.length !== 1) touchRef.current.singleTouch = false;
        if (isInteractionBlocked() || readerType !== 'pdf' || !pinchRef.current.active || event.touches.length < 2) return;
        const [first, second] = [event.touches[0], event.touches[1]];
        const distance = Math.hypot(second.clientX - first.clientX, second.clientY - first.clientY);
        pinchRef.current.nextZoom = readerPinchZoom(pinchRef.current.startZoom, pinchRef.current.startDistance, distance);
        event.preventDefault();
        event.stopPropagation();
      }}
      onTouchEnd={(event) => {
        if (isInteractionBlocked() || shouldIgnoreReaderInteraction(event.target)) return;
        if (readerType === 'pdf' && pinchRef.current.active) {
          if (event.touches.length >= 2) return;
          const nextZoom = Number(pinchRef.current.nextZoom.toFixed(2));
          pinchRef.current.active = false;
          suppressClickUntilRef.current = Date.now() + 450;
          updateSettings({ pdfZoom: nextZoom });
          return;
        }
        if (!touchRef.current.singleTouch) {
          suppressClickUntilRef.current = Date.now() + 450;
          return;
        }
        touchRef.current.singleTouch = false;
        const touch = event.changedTouches[0];
        if (!touch) return;
        const deltaX = touch.clientX - touchRef.current.x;
        const deltaY = touch.clientY - touchRef.current.y;
        const elapsed = Date.now() - touchRef.current.time;
        const swipeIntent = horizontalPaging === 'shell-discrete' && !zoomedPannable
          ? readerSwipeIntent(deltaX, deltaY, elapsed, readerDirectionRef.current)
          : null;
        if (swipeIntent) {
          suppressClickUntilRef.current = Date.now() + 450;
          handleInputIntent(swipeIntent);
          return;
        }
        if (Math.abs(deltaX) < 12 && Math.abs(deltaY) < 12) {
          suppressClickUntilRef.current = Date.now() + 450;
          handleReaderTap(touch.clientX, touch.clientY);
        } else if (horizontalPaging !== 'shell-discrete' || zoomedPannable) {
          suppressClickUntilRef.current = Date.now() + 450;
        }
      }}
      onTouchCancel={() => {
        pinchRef.current = { active: false, startDistance: 0, startZoom: settings.pdfZoom, nextZoom: settings.pdfZoom };
        touchRef.current = { x: 0, y: 0, time: 0, singleTouch: false };
        suppressClickUntilRef.current = Date.now() + 450;
      }}
      tabIndex={-1}
    >
      <main ref={readerViewportRef} className="min-h-0 flex-1 w-full overflow-hidden" data-reader-viewport="stable" {...inertWhen(Boolean(panel))}>
        {typeof children === 'function' ? children({ enterImmersive, toggleControls, escape: closePanelOrImmersive, shouldIgnoreInteraction: shouldIgnoreReaderInteraction, isInteractionBlocked }) : children}
      </main>

      {panel ? (
        <div
          aria-hidden="true"
          className="absolute inset-0 z-[25]"
          data-reader-panel-dismiss-layer="true"
          onClick={(event) => {
            event.stopPropagation();
            dismissPanelWithoutFocusRestore();
          }}
        />
      ) : null}

      <div
        className={cn(
          'pointer-events-none absolute inset-x-0 top-0 z-20 px-3 py-2 transition duration-200 motion-reduce:transition-none md:px-5',
          dark ? 'text-slate-100' : 'text-stone-900'
        )}
        style={{
          paddingTop: 'calc(0.5rem + var(--shuku-safe-area-top))',
          transform: controlsVisible ? 'translateY(0)' : 'translateY(-100%)',
          opacity: controlsVisible ? 1 : 0
        }}
        data-reader-control="true"
        data-reader-controller="top-minimal"
        aria-hidden={!controlsVisible || Boolean(panel)}
        {...inertWhen(!controlsVisible || Boolean(panel))}
        onClick={stopControlEvent}
      >
        <div
          className={cn('pointer-events-auto mx-auto flex h-12 w-full max-w-5xl items-center justify-between rounded-full border px-1 shadow-sm backdrop-blur-xl', dark ? 'border-white/10 bg-slate-950/75' : 'border-stone-200/80 bg-white/80')}
          data-reader-top-bar="true"
        >
          <button
            type="button"
            onClick={requestBackFromControl}
            onTouchEnd={requestBackFromControl}
            className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition active:scale-[0.97]', dark ? 'hover:bg-white/10' : 'hover:bg-stone-900/5')}
            aria-label={i18nAttribute("返回详情页")}
          >
            <ChevronLeft size={22} />
          </button>
          <button
            type="button"
            disabled={!canBookmark || !onToggleBookmark}
            onClick={() => toggleBookmark()}
            className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition active:scale-[0.97] disabled:opacity-40', dark ? 'hover:bg-white/10' : 'hover:bg-stone-900/5', bookmarkActive ? 'text-amber-600' : '')}
            aria-label={bookmarkActive ? i18nAttribute("快速移除当前书签") : i18nAttribute("快速添加书签")}
            aria-pressed={bookmarkActive}
          >
            <Bookmark size={19} fill={bookmarkActive ? 'currentColor' : 'none'} />
          </button>
        </div>
      </div>

      <div
        className="shuku-reader-bottom-bleed pointer-events-none absolute inset-x-0 z-10 px-3 py-3 transition duration-200 motion-reduce:transition-none md:px-5 md:py-4"
        style={{
          height: passiveProgressAreaHeight,
          paddingBottom: 'calc(0.75rem + var(--shuku-safe-area-bottom))',
          paddingLeft: 'calc(0.75rem + var(--shuku-safe-area-left))',
          paddingRight: 'calc(0.75rem + var(--shuku-safe-area-right))',
          transform: controlsVisible ? 'translateY(100%)' : 'translateY(0)',
          opacity: controlsVisible ? 0 : 1
        }}
        aria-hidden={controlsVisible}
      >
        <div className={cn('mx-auto flex h-full flex-col gap-3', readerBottomControlsMaxWidth)}>
          <div className="flex items-center justify-between gap-3 text-[11px] opacity-60 md:text-xs">
            <span className="truncate">{readerType === 'reflowable' ? (currentNavigationLabel ?? locationLabel ?? i18nAttribute("阅读中")) : progressPageLabel(progress)}</span>
            <span className="shrink-0 tabular-nums">{precisePercent(progress.percent, readerType, locale)}%</span>
          </div>
          <div className="min-h-0 flex-1" aria-hidden="true" />
        </div>
      </div>

      <div
        className={cn(
          'shuku-reader-bottom-bleed absolute inset-x-0 px-3 pt-2 transition duration-200 motion-reduce:transition-none md:px-5',
          panel ? 'z-40' : 'z-20',
          dark ? 'text-slate-100' : 'text-stone-900'
        )}
        style={{
          height: readerBottomAreaHeight,
          paddingBottom: 'calc(0.25rem + var(--shuku-safe-area-bottom))',
          transform: controlsVisible ? 'translateY(0)' : 'translateY(100%)',
          opacity: controlsVisible ? 1 : 0
        }}
        data-reader-control="true"
        data-reader-controller="bottom-console"
        aria-hidden={!controlsVisible}
        {...inertWhen(!controlsVisible)}
        onPointerDownCapture={(event) => {
          if (!panelRef.current) return;
          const target = event.target instanceof Element ? event.target : null;
          if (target?.closest('[data-reader-panel-trigger]')) return;
          if (target?.closest('button, input')) dismissPanelWithoutFocusRestore();
        }}
        onClick={stopControlEvent}
      >
        <div className={cn('relative mx-auto flex h-[4.75rem] items-stretch overflow-hidden rounded-[1.35rem] border shadow-[0_-10px_35px_rgba(41,28,17,0.12)] backdrop-blur-2xl md:h-[4.5rem] md:shadow-2xl', readerBottomControlsMaxWidth, dark ? 'border-white/10 bg-slate-950/90' : 'border-stone-200/90 bg-[#fffaf2]/95')}>
          <div className="pointer-events-none absolute inset-x-0 top-0 h-0.5 bg-current/10 md:hidden" aria-hidden="true">
            <div className="h-full" style={{ width: `${clampPercent(progress.percent)}%`, backgroundColor: accentColor }} />
          </div>
          {readerType !== 'reflowable' || navItems.length > 0 || volumeNavigation ? (
            <ReaderDockButton icon={ListTree} label={i18nAttribute("目录")} selected={panel === 'toc'} expanded={panel === 'toc'} panelTrigger="toc" onClick={(event) => togglePanel('toc', event.currentTarget)} dark={dark} />
          ) : null}
          <ReaderDockButton
            icon={Bookmark}
            label={i18nAttribute("书签")}
            ariaLabel={i18nAttribute("书签")}
            active={bookmarkActive}
            selected={panel === 'bookmarks'}
            expanded={panel === 'bookmarks'}
            panelTrigger="bookmarks"
            onClick={(event) => togglePanel('bookmarks', event.currentTarget)}
            dark={dark}
          />
          <ReaderDockButton icon={Gauge} label={i18nAttribute("进度")} prominent selected={panel === 'progress'} expanded={panel === 'progress'} panelTrigger="progress" onClick={(event) => togglePanel('progress', event.currentTarget)} dark={dark} className="md:hidden" />
          <div className="hidden min-w-0 flex-1 items-center gap-2 px-2 md:flex lg:px-4">
            <button type="button" aria-label={i18nAttribute("上一页")} disabled={!controls || capabilities?.canGoPrevious === false} onClick={() => { void controls?.prev(); keepControlsOpen(); }} className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition active:scale-[0.97] disabled:opacity-35', dark ? 'hover:bg-white/10' : 'hover:bg-stone-900/5')}>
              <ChevronLeft size={20} />
            </button>
            <div className="min-w-0 flex-1">
              <div className="mb-0.5 flex items-center justify-between gap-3 text-[11px] opacity-60">
                <span className="truncate">{currentNavigationLabel ?? locationLabel ?? progressPageLabel(progress)}</span>
                <span className="shrink-0 tabular-nums">{precisePercent(progress.percent, readerType, locale)}%</span>
              </div>
              <input
                aria-label={i18nAttribute("阅读进度")}
                type="range"
                min={0}
                max={100}
                value={progressScrubPercent ?? clampPercent(progress.percent)}
                disabled={!controls || capabilities?.canJumpToProgress === false}
                onChange={(event) => {
                  void jumpToPercent(Number(event.target.value), true);
                  keepControlsOpen();
                }}
                onBlur={flushPendingProgressJump}
                className="h-6 w-full min-w-0 cursor-pointer disabled:cursor-not-allowed"
                style={{ accentColor }}
              />
            </div>
            <button type="button" aria-label={i18nAttribute("下一页")} disabled={!controls || capabilities?.canGoNext === false} onClick={() => { void controls?.next(); keepControlsOpen(); }} className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition active:scale-[0.97] disabled:opacity-35', dark ? 'hover:bg-white/10' : 'hover:bg-stone-900/5')}>
              <ChevronRight size={20} />
            </button>
          </div>
          {supportsTextAnnotations ? <ReaderDockButton icon={Highlighter} label={i18nAttribute("标注")} ariaLabel={i18nAttribute("标注与批注")} selected={panel === 'annotations'} expanded={panel === 'annotations'} panelTrigger="annotations" onClick={(event) => togglePanel('annotations', event.currentTarget)} dark={dark} /> : null}
          <ReaderDockButton icon={Settings} label={i18nAttribute("显示")} ariaLabel={i18nAttribute("阅读设置")} selected={panel === 'settings'} expanded={panel === 'settings'} panelTrigger="settings" onClick={(event) => togglePanel('settings', event.currentTarget)} dark={dark} />
        </div>
      </div>

      {bookmarkNotice ? (
        <div role="status" className={cn('pointer-events-none absolute inset-x-0 z-30 mx-auto w-fit rounded-full border px-4 py-2 text-xs font-medium shadow-lg backdrop-blur-xl', dark ? 'border-white/10 bg-slate-950/90' : 'border-stone-200 bg-white/90')} style={{ bottom: 'calc(6rem + var(--shuku-safe-area-bottom))' }}>
          {bookmarkNotice}
        </div>
      ) : null}

      {panel ? (
        <aside
          ref={panelElementRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="reader-panel-title"
          tabIndex={-1}
          className={cn(
            'shuku-reader-mobile-panel fixed inset-x-0 z-30 flex w-full flex-col overflow-hidden overscroll-contain rounded-t-3xl border-t p-4 shadow-2xl backdrop-blur-2xl md:inset-x-auto md:left-5 md:rounded-3xl md:border md:p-5',
            (panel === 'toc' || panel === 'bookmarks') && 'shuku-reader-list-panel',
            panel === 'toc' || panel === 'bookmarks'
              ? 'md:w-[min(24rem,calc(100vw-2.5rem))]'
              : panel === 'settings'
                ? 'md:w-[min(24rem,calc(100vw-2.5rem))]'
                : 'md:w-[min(26rem,calc(100vw-2.5rem))]',
            dark ? 'border-white/10 bg-slate-950/95' : 'border-stone-200/90 bg-[#fffaf2]/95'
          )}
          style={{
            paddingTop: '1rem',
            paddingBottom: 'var(--shuku-reader-panel-padding-bottom)',
            paddingLeft: 'calc(1rem + var(--shuku-safe-area-left))',
            paddingRight: 'calc(1rem + var(--shuku-safe-area-right))',
            ...(panelPlacement ? { left: `${panelPlacement.left}px`, bottom: `${panelPlacement.bottom}px` } : {})
          }}
          data-reader-control="true"
          data-reader-panel={panel}
          id="reader-panel"
          onClick={stopControlEvent}
        >
          <div className="flex items-center justify-between gap-3">
            <div>
              <div id="reader-panel-title" className="text-sm font-semibold">
                {panel === 'toc'
                  ? i18nAttribute("目录")
                  : panel === 'bookmarks'
                    ? i18nAttribute("书签")
                    : panel === 'settings'
                      ? readerType === 'reflowable' ? i18nAttribute("小说排版") : i18nAttribute("阅读设置")
                      : panel === 'annotations' ? i18nAttribute("标注与批注") : i18nAttribute("阅读进度")}
              </div>
              {panel === 'settings' ? null : (
                <div className="mt-0.5 text-xs opacity-60">
                  {panel === 'bookmarks' ? i18nAttribute("{value0} 个书签", { value0: orderedBookmarks.length }) : progressDetail}
                </div>
              )}
            </div>
            <button type="button" onClick={() => { closePanel(); keepControlsOpen(); }} className="flex h-11 w-11 items-center justify-center rounded-full transition active:scale-[0.98] hover:bg-white/10" aria-label={i18nAttribute("关闭面板")}>
              <X size={18} />
            </button>
          </div>

          {panel === 'toc' && volumeNavigation ? (
            <VolumeNavigationPanel
              navigation={volumeNavigation}
              readerType={readerType}
              activeItemKey={currentNavigationItem ? navigationItemKey(currentNavigationItem) : null}
              dark={dark}
              onJumpItem={(item) => {
                volumeNavigation.onSelectItem(item);
                closePanel();
                keepControlsOpen();
              }}
            />
          ) : null}

          {panel === 'toc' && !volumeNavigation ? (
            <div data-pwa-scroll="true" className="mt-5 min-h-0 flex-1 overflow-auto overscroll-contain pr-1">
              {navItems.length === 0 ? <div className="py-6 text-sm opacity-60"><I18nText>暂无可跳转条目</I18nText></div> : null}
              <div className="space-y-1">
                {navItems.map((item) => (
                  <button
                    key={`${item.index}-${item.title}`}
                    type="button"
                    aria-current={currentNavigationItem && navigationItemKey(item) === navigationItemKey(currentNavigationItem) ? 'location' : undefined}
                    onClick={() => { void jumpToItem(item); }}
                    className={cn('flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition active:scale-[0.99]', currentNavigationItem && navigationItemKey(item) === navigationItemKey(currentNavigationItem) ? 'bg-amber-700 text-white' : 'hover:bg-white/10')}
                  >
                    <span className="w-9 shrink-0 tabular-nums opacity-60">{item.index}</span>
                    <span className="line-clamp-2">{item.title}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {panel === 'bookmarks' ? (
            <div className="mt-3 flex min-h-0 flex-1 flex-col">
              <button
                type="button"
                disabled={!canBookmark || !onToggleBookmark}
                onClick={() => toggleBookmark(false)}
                className={cn(
                  'flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-xl border px-3 text-sm font-medium transition active:scale-[0.98] disabled:opacity-40',
                  bookmarkActive
                    ? dark ? 'border-amber-400/30 bg-amber-400/10 text-amber-300' : 'border-amber-700/20 bg-amber-700/10 text-amber-800'
                    : dark ? 'border-white/10 hover:bg-white/10' : 'border-stone-900/10 hover:bg-stone-900/5'
                )}
                aria-label={bookmarkActive ? i18nAttribute("移除当前位置书签") : i18nAttribute("添加当前位置书签")}
              >
                <Bookmark size={16} fill={bookmarkActive ? 'currentColor' : 'none'} />
                {bookmarkActive ? i18nAttribute("移除当前位置") : i18nAttribute("添加当前位置")}
              </button>
              <div data-pwa-scroll="true" className="mt-3 min-h-0 flex-1 overflow-auto overscroll-contain pr-1">
                {orderedBookmarks.length === 0 ? (
                  <div className="flex min-h-32 flex-col items-center justify-center rounded-2xl border border-dashed border-current/15 px-5 text-center">
                    <Bookmark size={22} className="opacity-35" />
                    <div className="mt-2 text-sm font-medium"><I18nText>还没有书签</I18nText></div>
                    <div className="mt-1 text-xs opacity-55"><I18nText>保存当前位置后，可从这里快速返回</I18nText></div>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {orderedBookmarks.map((bookmark) => {
                      const active = bookmark.id === currentBookmarkId;
                      const dateLabel = bookmarkDateLabel(bookmark.createdAt, locale);
                      return (
                        <div key={bookmark.id} className={cn('flex min-h-12 items-stretch rounded-xl transition', active ? dark ? 'bg-amber-400/10 text-amber-300' : 'bg-amber-700/10 text-amber-800' : dark ? 'bg-white/[0.06]' : 'bg-stone-900/[0.04]')}>
                          <button
                            type="button"
                            onClick={() => { void jumpToBookmark(bookmark); }}
                            className="min-w-0 flex-1 px-3 py-2.5 text-left active:scale-[0.99]"
                            aria-label={i18nAttribute("跳转到书签：{value0}", { value0: bookmark.label })}
                          >
                            <span className="block truncate text-sm font-medium">{i18nAttribute(bookmark.label)}</span>
                            <span className="mt-0.5 flex items-center gap-2 text-[11px] opacity-55">
                              <span className="tabular-nums">{clampPercent(bookmark.percent)}%</span>
                              {dateLabel ? <span>{dateLabel}</span> : null}
                              {active ? <span><I18nText>当前位置</I18nText></span> : null}
                            </span>
                          </button>
                          {onRemoveBookmark ? (
                            <button
                              type="button"
                              onClick={() => onRemoveBookmark(bookmark.id)}
                              className={cn('flex w-11 shrink-0 items-center justify-center rounded-xl transition active:scale-[0.96]', dark ? 'hover:bg-white/10' : 'hover:bg-stone-900/5')}
                              aria-label={i18nAttribute("删除书签：{value0}", { value0: bookmark.label })}
                            >
                              <Trash2 size={15} />
                            </button>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          ) : null}

          {panel === 'progress' ? (
            <div className="mt-6 space-y-5">
              <div className="text-center">
                <div className="text-3xl font-semibold tabular-nums">{precisePercent(progress.percent, readerType, locale)}%</div>
                <div className="mt-1 text-xs opacity-60">{currentNavigationLabel ?? progressPageLabel(progress)}</div>
                {locationLabel ? <div className="mt-2 text-sm tabular-nums opacity-75">{locationLabel}</div> : null}
                {sectionRemaining || totalRemaining ? (
                  <div className="mt-2 flex flex-wrap justify-center gap-x-3 gap-y-1 text-xs opacity-60">
                    {sectionRemaining ? <span>{i18nAttribute('本节剩余：{value0}', { value0: sectionRemaining })}</span> : null}
                    {totalRemaining ? <span>{i18nAttribute('全书剩余：{value0}', { value0: totalRemaining })}</span> : null}
                  </div>
                ) : null}
              </div>
              <input
                aria-label={i18nAttribute("阅读进度")}
                type="range"
                min={0}
                max={100}
                value={progressScrubPercent ?? clampPercent(progress.percent)}
                disabled={!controls || capabilities?.canJumpToProgress === false}
                onChange={(event) => void jumpToPercent(Number(event.target.value), true)}
                onBlur={flushPendingProgressJump}
                className="h-12 w-full cursor-pointer disabled:cursor-not-allowed"
                style={{ accentColor }}
              />
              <div className="grid grid-cols-2 gap-3">
                <Button aria-label={i18nAttribute("上一页")} disabled={!controls || capabilities?.canGoPrevious === false} variant="ghost" icon={ChevronLeft} className={cn('min-h-12 border border-current/10', dark ? 'text-slate-100 hover:bg-white/10' : '')} onClick={() => { void controls?.prev(); keepControlsOpen(); }}><I18nText>上一页</I18nText></Button>
                <Button aria-label={i18nAttribute("下一页")} disabled={!controls || capabilities?.canGoNext === false} variant="ghost" icon={ChevronRight} className={cn('min-h-12 border border-current/10', dark ? 'text-slate-100 hover:bg-white/10' : '')} onClick={() => { void controls?.next(); keepControlsOpen(); }}><I18nText>下一页</I18nText></Button>
              </div>
            </div>
          ) : null}

          {panel === 'annotations' ? (
            <div className="mt-5 min-h-0 flex-1">
              <div className={cn('grid grid-cols-2 gap-1 rounded-2xl p-1', dark ? 'bg-white/10' : 'bg-stone-900/5')} role="tablist" aria-label={i18nAttribute("标注分类")}>
                <button type="button" role="tab" aria-selected={annotationTab === 'book'} onClick={() => setAnnotationTab('book')} className={cn('min-h-11 rounded-xl px-3 text-sm font-medium transition', annotationTab === 'book' ? dark ? 'bg-white/15 shadow-sm' : 'bg-white text-amber-800 shadow-sm' : 'opacity-60')}><I18nText>书内注释</I18nText></button>
                <button type="button" role="tab" aria-selected={annotationTab === 'mine'} onClick={() => setAnnotationTab('mine')} className={cn('min-h-11 rounded-xl px-3 text-sm font-medium transition', annotationTab === 'mine' ? dark ? 'bg-white/15 shadow-sm' : 'bg-white text-amber-800 shadow-sm' : 'opacity-60')}><I18nText>我的标注</I18nText></button>
              </div>
              <div role="tabpanel" data-pwa-scroll="true" className="mt-4 min-h-0 overflow-auto rounded-2xl border border-current/10 p-5 text-center">
                <Highlighter className="mx-auto opacity-45" size={24} />
                <div className="mt-3 text-sm font-medium">{annotationTab === 'book' ? i18nAttribute("暂无可展示的书内注释") : i18nAttribute("还没有划线或批注")}</div>
                <p className="mx-auto mt-2 max-w-xs text-xs leading-5 opacity-60">
                  {annotationTab === 'book'
                    ? i18nAttribute("当前版本尚未建立注释索引；后续接入 EPUB 脚注与尾注解析后会集中显示在这里。")
                    : i18nAttribute("划线、批注与跨设备同步的数据层尚未接入；这里先保留统一入口与完整的响应式结构。")}
                </p>
              </div>
            </div>
          ) : null}

          {panel === 'settings' ? (
            <div data-pwa-scroll="true" className="mt-3 min-h-0 flex-1 space-y-3 overflow-auto overscroll-contain pr-1 text-sm">
              {readerType === 'reflowable' ? (
                <>
                  <ThemeSwatches
                    value={settings.theme}
                    onChange={(value) => updateSettings({ theme: value as ReaderTheme })}
                    dark={dark}
                  />
                  <CompactSettingOptions
                    label={i18nAttribute("字号")}
                    value={closestReaderOptionValue(settings.fontSize, readerFontSizeOptions)}
                    options={readerFontSizeOptions}
                    disambiguateLabels
                    onChange={(value) => updateSettings({ fontSize: Number(value) })}
                    dark={dark}
                  />
                  <CompactSettingOptions
                    label={i18nAttribute("行距")}
                    value={closestReaderOptionValue(settings.lineHeight, readerLineHeightOptions)}
                    options={readerLineHeightOptions}
                    disambiguateLabels
                    onChange={(value) => updateSettings({ lineHeight: Number(value) })}
                    dark={dark}
                  />
                  <CompactSettingOptions
                    label={i18nAttribute("字体")}
                    value={settings.fontFamily}
                    options={READER_FONT_FAMILY_OPTIONS}
                    onChange={(value) => updateSettings({ fontFamily: value as ReaderFontFamily })}
                    dark={dark}
                  />
                  <CompactSettingOptions
                    label={i18nAttribute("页宽")}
                    value={closestReaderOptionValue(settings.pageWidth, READER_PAGE_WIDTH_OPTIONS)}
                    options={READER_PAGE_WIDTH_OPTIONS}
                    onChange={(value) => updateSettings({ pageWidth: Number(value) })}
                    dark={dark}
                  />
                  <CompactSettingOptions
                    label={i18nAttribute("排版")}
                    value={settings.ebookFlow}
                    options={READER_FLOW_OPTIONS}
                    onChange={(value) => updateSettings({ ebookFlow: value as EbookFlow })}
                    dark={dark}
                  />
                </>
              ) : readerType === 'comic' ? (
                <>
                  <ThemeSwatches
                    value={settings.theme}
                    onChange={(value) => updateSettings({ theme: value as ReaderTheme })}
                    dark={dark}
                  />
                  <CompactSettingOptions
                    label={i18nAttribute("模式")}
                    value={settings.comicMode}
                    options={READER_SPREAD_MODE_OPTIONS}
                    onChange={(value) => updateSettings({ comicMode: value as ComicMode })}
                    dark={dark}
                  />
                  <CompactSettingOptions
                    label={i18nAttribute("翻页")}
                    value={settings.comicPageTurnAnimation}
                    options={READER_PAGE_TURN_ANIMATION_OPTIONS}
                    onChange={(value) => updateSettings({ comicPageTurnAnimation: value as ComicPageTurnAnimation })}
                    dark={dark}
                  />
                  <CompactSettingOptions
                    label={i18nAttribute("适配")}
                    value={settings.imageFit}
                    options={READER_COMIC_IMAGE_FIT_OPTIONS}
                    onChange={(value) => updateSettings({ imageFit: value as ComicImageFit })}
                    dark={dark}
                  />
                  <CompactSettingOptions
                    label={i18nAttribute("画质")}
                    value={settings.imageVariant}
                    options={READER_COMIC_IMAGE_VARIANT_OPTIONS}
                    onChange={(value) => updateSettings({ imageVariant: value as ComicImageVariant })}
                    dark={dark}
                  />
                  <CompactSettingOptions
                    label={i18nAttribute("方向")}
                    value={settings.comicDirection}
                    options={READER_COMIC_DIRECTION_OPTIONS}
                    onChange={(value) => updateSettings({ comicDirection: value as ComicDirection })}
                    dark={dark}
                  />
                  {capabilities?.canZoom !== false ? <CompactStepper label={i18nAttribute("缩放")} value={`${Math.round(settings.comicZoom * 100)}%`} onMinus={() => updateSettings({ comicZoom: Math.max(0.6, Number((settings.comicZoom - 0.1).toFixed(1))) })} onPlus={() => updateSettings({ comicZoom: Math.min(2.4, Number((settings.comicZoom + 0.1).toFixed(1))) })} dark={dark} /> : null}
                </>
              ) : (
                <>
                  <ThemeSwatches
                    value={settings.theme}
                    onChange={(value) => updateSettings({ theme: value as ReaderTheme })}
                    dark={dark}
                  />
                  {capabilities?.canZoom !== false ? <CompactStepper label={i18nAttribute("缩放")} value={`${Math.round(settings.pdfZoom * 100)}%`} onMinus={() => updateSettings({ pdfZoom: Math.max(0.6, Number((settings.pdfZoom - 0.1).toFixed(1))) })} onPlus={() => updateSettings({ pdfZoom: Math.min(2.4, Number((settings.pdfZoom + 0.1).toFixed(1))) })} dark={dark} /> : null}
                  <CompactSettingOptions
                    label={i18nAttribute("适配")}
                    value={settings.pdfFit}
                    options={READER_PDF_FIT_OPTIONS}
                    onChange={(value) => updateSettings({ pdfFit: value as PdfFit })}
                    dark={dark}
                  />
                </>
              )}
              {onResetSettings ? (
                <button
                  type="button"
                  onClick={() => { void onResetSettings(); keepControlsOpen(); }}
                  aria-label={i18nAttribute("恢复本书默认设置")}
                  className={cn('flex min-h-10 w-full items-center justify-center gap-2 rounded-xl border border-current/10 px-3 text-xs font-medium transition active:scale-[0.98]', dark ? 'hover:bg-white/10' : 'hover:bg-stone-900/5')}
                >
                  <RotateCcw size={15} />
                  <I18nText>恢复默认</I18nText></button>
              ) : null}
            </div>
          ) : null}
        </aside>
      ) : null}
      </div>
    </div>
  );
}

function ReaderDockButton({ icon: Icon, label, ariaLabel, active = false, selected = false, expanded, panelTrigger, prominent = false, disabled = false, onClick, dark, className }: {
  icon: LucideIcon;
  label: string;
  ariaLabel?: string;
  active?: boolean;
  selected?: boolean;
  expanded?: boolean;
  panelTrigger?: ReaderPanel;
  prominent?: boolean;
  disabled?: boolean;
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
  dark: boolean;
  className?: string;
}) {
  const { t: i18nAttribute } = useAttributeI18n();
  return (
    <button
      type="button"
      aria-label={ariaLabel ?? label}
      aria-pressed={active || undefined}
      aria-expanded={expanded}
      aria-controls={expanded ? 'reader-panel' : undefined}
      data-reader-panel-trigger={panelTrigger}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'group flex min-w-0 flex-1 rounded-2xl p-1.5 text-[11px] font-medium transition active:scale-[0.97] disabled:pointer-events-none disabled:opacity-35 md:w-[4.75rem] md:flex-none',
        selected
          ? dark ? 'text-amber-400' : 'text-amber-700'
          : active ? 'text-amber-600' : '',
        className
      )}
    >
      <span
        data-reader-dock-surface="true"
        data-reader-dock-selection-surface={selected ? 'true' : undefined}
        className={cn(
          'flex h-full min-w-0 w-full flex-col items-center justify-center gap-1 rounded-[0.95rem] px-1 transition-colors',
          selected
            ? dark ? 'bg-white/10' : 'bg-amber-700/10'
            : dark ? 'group-hover:bg-white/10' : 'group-hover:bg-stone-900/5'
        )}
      >
        <span className={cn('flex items-center justify-center', prominent ? 'h-9 w-9 rounded-full bg-amber-700 text-white shadow-sm' : '')}>
          <Icon size={prominent ? 18 : 19} strokeWidth={1.8} fill={active ? 'currentColor' : 'none'} />
        </span>
        <span className="max-w-full truncate">{i18nAttribute(label)}</span>
      </span>
    </button>
  );
}

function ThemeSwatches({ value, onChange, dark }: { value: ReaderTheme; onChange: (value: ReaderTheme) => void; dark: boolean }) {
  const { t: i18nAttribute } = useAttributeI18n();
  return (
    <div role="group" aria-label={i18nAttribute("主题")} className={cn('flex items-center justify-center gap-3 rounded-2xl p-1.5', dark ? 'bg-white/[0.06]' : 'bg-stone-900/[0.04]')}>
      {READER_THEME_OPTIONS.map((option) => {
        const selected = value === option.value;
        const surface = readerThemeSurfaces[option.value];
        return (
          <button
            key={option.value}
            type="button"
            aria-label={i18nAttribute(option.label)}
            aria-pressed={selected}
            onClick={() => onChange(option.value)}
            className={cn('flex h-11 w-11 items-center justify-center rounded-full border-2 border-transparent p-1 transition active:scale-[0.96]', selected ? dark ? 'border-amber-400/80' : 'border-amber-700/70' : dark ? 'hover:border-white/15' : 'hover:border-stone-900/10')}
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-full border border-black/10 shadow-sm" style={{ backgroundColor: surface.background, color: surface.color }}>
              {selected ? <Check size={14} strokeWidth={2.5} /> : null}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function CompactSettingOptions({ label, value, options, onChange, dark, disabled = false, disambiguateLabels = false }: {
  label: string;
  value: string;
  options: ReadonlyArray<{ value: string; label: string; icon?: LucideIcon }>;
  onChange: (value: string) => void;
  dark: boolean;
  disabled?: boolean;
  disambiguateLabels?: boolean;
}) {
  const { t: i18nAttribute } = useAttributeI18n();
  return (
    <div className={cn('flex items-center gap-3', disabled && 'opacity-45')}>
      <span className="w-9 shrink-0 text-xs font-medium opacity-55">{i18nAttribute(label)}</span>
      <div
        role="group"
        aria-label={i18nAttribute(label)}
        className={cn('grid min-w-0 flex-1 gap-1 rounded-xl p-1', dark ? 'bg-white/[0.07]' : 'bg-stone-900/[0.05]')}
        style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
        aria-disabled={disabled}
      >
        {options.map((option) => {
          const Icon = option.icon;
          const selected = value === option.value;
          return (
            <button
              key={option.value}
              type="button"
              aria-label={i18nAttribute(disambiguateLabels ? `${label}${option.label}` : option.label)}
              aria-pressed={selected}
              disabled={disabled}
              onClick={() => onChange(option.value)}
              className={cn(
                'flex min-h-9 min-w-0 items-center justify-center gap-1 rounded-lg px-1 text-xs font-medium transition active:scale-[0.97]',
                selected
                  ? dark ? 'bg-white/15 text-amber-300 shadow-sm' : 'bg-white text-amber-800 shadow-sm'
                  : dark ? 'opacity-65 hover:bg-white/[0.07] hover:opacity-100' : 'opacity-60 hover:bg-white/55 hover:opacity-100'
              )}
            >
              {Icon ? <Icon size={15} strokeWidth={1.8} /> : null}
              <span className="truncate">{i18nAttribute(option.label)}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function CompactStepper({ label, value, onMinus, onPlus, dark }: { label: string; value: string; onMinus: () => void; onPlus: () => void; dark: boolean }) {
  const { t: i18nAttribute } = useAttributeI18n();
  return (
    <div className="flex items-center gap-3">
      <span className="w-9 shrink-0 text-xs font-medium opacity-55">{i18nAttribute(label)}</span>
      <div className={cn('flex min-w-0 flex-1 items-center rounded-xl p-1', dark ? 'bg-white/[0.07]' : 'bg-stone-900/[0.05]')}>
        <button type="button" onClick={onMinus} className={cn('flex h-9 w-9 items-center justify-center rounded-lg transition active:scale-[0.97]', dark ? 'hover:bg-white/10' : 'hover:bg-white/60')} aria-label={i18nAttribute("{value0}减少", { value0: label })}>
          <Minus size={14} />
        </button>
        <span className="min-w-14 flex-1 text-center text-xs tabular-nums">{value}</span>
        <button type="button" onClick={onPlus} className={cn('flex h-9 w-9 items-center justify-center rounded-lg transition active:scale-[0.97]', dark ? 'hover:bg-white/10' : 'hover:bg-white/60')} aria-label={i18nAttribute("{value0}增加", { value0: label })}>
          <Plus size={14} />
        </button>
      </div>
    </div>
  );
}

function VolumeNavigationPanel({ navigation, readerType, activeItemKey, dark, onJumpItem }: { navigation: ReaderVolumeNavigation; readerType: ReaderKind; activeItemKey: string | null; dark: boolean; onJumpItem: (item: ReaderNavigationItem) => void }) {
  const { t: i18nAttribute } = useAttributeI18n();
  const showVolumes = navigation.volumeSections.length > 1;
  const idleText = navigation.loading ? '正在切换...' : null;
  const isComic = readerType === 'comic';

  return (
    <div data-pwa-scroll="true" className="mt-5 min-h-0 flex-1 overflow-auto overscroll-contain pr-1">
      {idleText ? <div className="mb-3 rounded-xl bg-white/10 px-3 py-2 text-xs opacity-70">{idleText}</div> : null}
      {showVolumes && !isComic ? (
        <VolumeNavigationGroup title={i18nAttribute("卷册")}>
          <VolumeSelect
            items={navigation.volumeSections.map((volume, index) => ({
              id: volume.id,
              title: volume.title || i18nAttribute("第 {value0} 卷", { value0: index + 1 })
            }))}
            value={navigation.currentVolumeId}
            onChange={navigation.onSelectVolume}
            disabled={navigation.loading}
            dark={dark}
            className="w-full"
          />
        </VolumeNavigationGroup>
      ) : null}

      {showVolumes && isComic ? (
        <VolumeNavigationGroup title={isComic ? i18nAttribute("卷/话") : i18nAttribute("卷册")}>
          {navigation.volumeSections.map((volume, index) => (
            <button
              key={volume.id}
              type="button"
              disabled={navigation.loading}
              onClick={() => navigation.onSelectVolume(volume.id)}
              className={comicNavButtonClass(volume.id === navigation.currentVolumeId, dark)}
            >
              <span className="w-8 shrink-0 tabular-nums opacity-60">{index + 1}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{volume.title || i18nAttribute("第 {value0} {value1}", { value0: index + 1, value1: isComic ? '话' : '卷' })}</span>
                <span className="mt-0.5 block truncate text-xs opacity-65">{volume.pageCount || 0} {isComic ? i18nAttribute("页") : i18nAttribute("章")}</span>
              </span>
            </button>
          ))}
        </VolumeNavigationGroup>
      ) : null}

      <VolumeNavigationGroup title={isComic ? (showVolumes ? i18nAttribute("当前卷页码") : i18nAttribute("页码")) : (showVolumes ? i18nAttribute("当前卷章节") : i18nAttribute("章节"))}>
        {navigation.pages.length === 0 ? <div className="py-6 text-sm opacity-60">{isComic ? i18nAttribute("暂无可跳转页码") : i18nAttribute("暂无可跳转章节")}</div> : null}
        <div className={isComic ? 'grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-3' : 'space-y-1'}>
          {navigation.pages.map((item) => (
            <button
              key={`${item.index}-${item.title}`}
              type="button"
              aria-current={activeItemKey && navigationItemKey(item) === activeItemKey ? 'location' : undefined}
              disabled={navigation.loading}
              onClick={() => onJumpItem(item)}
              className={cn(
                isComic ? 'min-h-11 rounded-xl px-2 text-sm tabular-nums transition active:scale-[0.98] disabled:cursor-wait disabled:opacity-60' : 'flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition active:scale-[0.99] disabled:cursor-wait disabled:opacity-60',
                activeItemKey && navigationItemKey(item) === activeItemKey ? 'bg-amber-700 text-white' : dark ? 'bg-white/10 hover:bg-white/15' : 'bg-stone-100 hover:bg-stone-200'
              )}
            >
              {isComic ? item.index : (
                <>
                  <span className="w-9 shrink-0 tabular-nums opacity-60">{item.index}</span>
                  <span className="line-clamp-2">{item.title}</span>
                </>
              )}
            </button>
          ))}
        </div>
      </VolumeNavigationGroup>
    </div>
  );
}

function VolumeNavigationGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-5">
      <div className="mb-2 text-xs font-semibold uppercase opacity-50">{title}</div>
      <div className="space-y-1">{children}</div>
    </section>
  );
}

function comicNavButtonClass(selected: boolean, dark: boolean) {
  return cn(
    'flex min-h-12 w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition active:scale-[0.99] disabled:cursor-wait disabled:opacity-60',
    selected ? 'bg-amber-700 text-white' : dark ? 'hover:bg-white/10' : 'hover:bg-stone-100'
  );
}

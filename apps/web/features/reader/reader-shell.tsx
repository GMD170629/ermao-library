'use client';

import {
  READER_SETTINGS_CATALOG,
  changeReaderSetting,
  readerPhysicalHorizontalPageTurn,
  readerSettingAvailability,
  readerSettingValue,
  type ReaderCapabilities,
  type ReaderKind,
  type ReaderPreferences,
  type ReaderSettingId
} from '@shuku/reader-core';
import { preferencesToReaderSettings, readerSettingsToPreferences } from './v3/presentation';

import { BookOpen, Bookmark, Check, ChevronDown, ChevronLeft, ChevronRight, Highlighter, ListTree, Minus, NotebookPen, Palette, Plus, Settings, SlidersHorizontal, Trash2, Type, X, type LucideIcon } from 'lucide-react';
import { useEffect, useId, useRef, useState, type CSSProperties, type MouseEvent, type ReactNode, type SyntheticEvent } from 'react';
import { cn } from '../../components/ui/cn';
import { ResourceSelect } from '../../components/ui/resource-select';
import { useI18n } from '../../i18n/provider';
import { isDarkReaderTheme, readerThemeSurfaces } from './reader-theme';
import type { ReaderBookmark } from './v3/bookmarks';
import { resolveActiveEpubNavigationIndex } from './v3/epub-navigation';
import type { ReaderInteractionPolicy } from './v3/adapters/reader-interaction';
import { hasActiveTextSelection, isReaderControlTarget, isReaderKeyboardControlTarget, ReaderKeyboardNavigationController, readerKeyIntent, readerPinchZoom, readerPointerIntentInViewport, readerSwipeIntent, type ReaderInputIntent } from './v3/input-router';
import {
  MOBILE_READER_VIEWPORT_MAXIMUM,
  readerPageWidthSliderMaximum
} from './v3/page-width';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import { ReaderControlNavButton, ReaderSegmentedControl } from './ui/reader-control-primitives';
import { createScreenWakeLockController, readerWakeLockPort } from './screen-wake-lock';

type ComicDirection = ReaderPreferences['comic']['direction'];
type ComicMode = ReaderPreferences['comic']['spreadMode'];
type ComicPageTurnAnimation = ReaderPreferences['comic']['pageTurnAnimation'];
type ComicImageFit = ReaderPreferences['comic']['imageFit'];
type ComicImageVariant = ReaderPreferences['comic']['imageVariant'];

type ReaderTheme = ReaderPreferences['appearance']['theme'];
type EbookPageTurnAnimation = ReaderPreferences['epub']['pageTurnAnimation'];
type EbookSpreadMode = ReaderPreferences['epub']['spreadMode'];
type EbookFlow = ReaderPreferences['epub']['flow'];
type PdfFit = ReaderPreferences['pdf']['fit'];

export type ReaderProgress = {
  page: number;
  total: number | null;
  percent: number;
  position: string;
  label: string;
};

export type ReaderControls = {
  next: () => Promise<boolean>;
  prev: () => Promise<boolean>;
  jumpToProgress: (value: number) => Promise<boolean>;
  jumpToHref?: (href: string) => Promise<boolean>;
  jumpToIndex?: (index: number) => Promise<boolean>;
};

export type ReaderSettings = {
  theme: ReaderTheme;
  manualTheme: ReaderTheme;
  themeMode: ReaderPreferences['appearance']['themeMode'];
  progressStyle: ReaderPreferences['display']['progressStyle'];
  showClock: boolean;
  tapZones: ReaderPreferences['interaction']['tapZones'];
  swipePageTurn: boolean;
  keyboardPageTurn: boolean;
  volumeKeyPageTurn: boolean;
  keepScreenAwake: boolean;
  readingProgression: ReaderPreferences['epub']['readingProgression'];
  writingMode: ReaderPreferences['epub']['writingMode'];
  fontSize: number;
  lineHeight: number;
  pageWidth: number;
  fontFamily: ReaderPreferences['epub']['fontFamily'];
  fontWeight: ReaderPreferences['epub']['fontWeight'];
  letterSpacing: ReaderPreferences['epub']['letterSpacing'];
  pageMargin: ReaderPreferences['epub']['pageMargin'];
  ebookPageTurnAnimation: EbookPageTurnAnimation;
  ebookSpreadMode: EbookSpreadMode;
  ebookFlow: EbookFlow;
  paragraphIndent: number;
  paragraphSpacing: number;
  textAlign: ReaderPreferences['epub']['typography']['textAlign'];
  preservePublisherStyles: boolean;
  smartOptimization: boolean;
  deduplicateIndent: boolean;
  indentUnindented: boolean;
  comicZoom: number;
  comicPageWidth: number;
  pdfZoom: number;
  pdfPageWidth: number;
  comicDirection: ComicDirection;
  comicMode: ComicMode;
  comicPageTurnAnimation: ComicPageTurnAnimation;
  imageFit: ComicImageFit;
  imageVariant: ComicImageVariant;
  comicFlow: ReaderPreferences['comic']['flow'];
  comicCoverSingle: boolean;
  comicPageGap: ReaderPreferences['comic']['pageGap'];
  pdfFit: PdfFit;
  pdfFlow: ReaderPreferences['pdf']['flow'];
  pdfRotation: ReaderPreferences['pdf']['rotation'];
  pdfCropMargins: ReaderPreferences['pdf']['cropMargins'];
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
  resourceNavigation?: ReaderResourceNavigation;
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

export type ReaderResourceNavigation = {
  resourceSections: Array<{ id: string; title: string; pageCount: number }>;
  pages: ReaderNavigationItem[];
  currentResourceId: string;
  loading: boolean;
  onSelectResource: (resourceId: string) => void;
  onSelectItem: (item: ReaderNavigationItem) => void;
};

const readerBottomAreaHeight = 'calc(5.75rem + var(--shuku-safe-area-bottom))';
const readerBottomControlsMaxWidth = 'max-w-5xl';
const progressJumpDebounceMs = 160;
type ReaderPanel = 'toc' | 'bookmarks' | 'notes' | 'appearance' | 'settings' | 'annotations';

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
  const sectionIndex = numberFromExtra(progressExtra.sectionIndex);
  const index = resolveActiveEpubNavigationIndex(items, href, sectionIndex);
  if (index !== null) return items[index] ?? null;
  const chapterIndex = numberFromExtra(progressExtra.chapterIndex);
  if (chapterIndex !== null) {
    return items.find((item) => item.index === chapterIndex) ?? items[Math.floor(chapterIndex)] ?? null;
  }
  return sectionIndex === null ? null : items[Math.floor(sectionIndex)] ?? null;
}

function precisePercent(value: number, readerType: ReaderKind, locale: string) {
  const safe = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: readerType === 'reflowable' ? 1 : 0,
    maximumFractionDigits: readerType === 'reflowable' ? 1 : 0
  }).format(safe);
}

function logicalLocationLabel(extra: Record<string, unknown>) {
  const current = numberFromExtra(extra.locationCurrent);
  const next = numberFromExtra(extra.locationNext);
  const total = numberFromExtra(extra.locationTotal);
  if (current === null || next === null || total === null || total < 1) return null;
  const start = Math.min(total, Math.floor(current) + 1);
  const end = Math.min(total, Math.max(start, Math.floor(next) + 1));
  return start === end ? `Loc ${start} / ${total}` : `Loc ${start}–${end} / ${total}`;
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

function secondsValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function remainingTimeLabel(seconds: number, locale: string) {
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  if (minutes < 60) return locale === 'zh-CN' ? `剩余 ${minutes} 分钟` : `${minutes} min left`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return locale === 'zh-CN'
    ? `剩余 ${hours} 小时${remainder ? ` ${remainder} 分钟` : ''}`
    : `${hours} hr${remainder ? ` ${remainder} min` : ''} left`;
}

export function ReaderShell({ readerType, progress, progressExtra = {}, controls, settings, capabilities = null, readingDirection, onBack, onSettingsChange, onResetSettings, interactionBlocked = false, horizontalPaging = 'shell-discrete', navigationItems, resourceNavigation, bookmarkActive = false, currentBookmarkId = null, bookmarks = [], canBookmark = false, onToggleBookmark, onJumpBookmark, onRemoveBookmark, children }: ReaderShellProps) {
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
  const settingsRef = useRef(settings);
  const handleInputIntentRef = useRef<(intent: ReaderInputIntent | null) => void | Promise<void>>(() => undefined);
  const keyboardNavigationRef = useRef(new ReaderKeyboardNavigationController());
  const panelElementRef = useRef<HTMLDivElement | null>(null);
  const panelReturnFocusRef = useRef<HTMLElement | null>(null);
  const [controlsVisible, setControlsVisible] = useState(false);
  const [panel, setPanel] = useState<ReaderPanel | null>(null);
  const [annotationTab, setAnnotationTab] = useState<'book' | 'mine'>('book');
  const [notesTab, setNotesTab] = useState<'bookmarks' | 'annotations'>('bookmarks');
  const [bookmarkNotice, setBookmarkNotice] = useState('');
  const [clockTime, setClockTime] = useState(() => new Date());
  const [readerViewportWidth, setReaderViewportWidth] = useState(1350);
  const wakeLockPort = typeof navigator === 'undefined' ? null : readerWakeLockPort(navigator);
  const wakeLockSupported = wakeLockPort !== null;
  const navItems = navigationItems ?? [];
  const orderedBookmarks = [...bookmarks].sort((left, right) => (
    left.position.presentation.displayPercent - right.position.presentation.displayPercent
    || left.createdAt.localeCompare(right.createdAt)
  ));
  const [progressScrubPercent, setProgressScrubPercent] = useState<number | null>(null);
  const dark = isDarkReaderTheme(settings.theme);
  const themeSurface = readerThemeSurfaces[settings.theme];
  const availableNavigationItems = navItems.length > 0 ? navItems : resourceNavigation?.pages ?? [];
  const chapterNavigationItems = availableNavigationItems;
  const currentNavigationItem = activeNavigationItem(readerType, chapterNavigationItems, progress, progressExtra);
  const currentNavigationIndex = currentNavigationItem
    ? chapterNavigationItems.findIndex((item) => navigationItemKey(item) === navigationItemKey(currentNavigationItem))
    : -1;
  const previousChapter = currentNavigationIndex > 0 ? chapterNavigationItems[currentNavigationIndex - 1] ?? null : null;
  const nextChapter = currentNavigationIndex >= 0 && currentNavigationIndex < chapterNavigationItems.length - 1
    ? chapterNavigationItems[currentNavigationIndex + 1] ?? null
    : null;
  const currentNavigationTitle = currentNavigationItem?.title ?? null;
  const currentNavigationLabel = currentNavigationTitle;
  const locationLabel = readerType === 'reflowable' ? logicalLocationLabel(progressExtra) : null;
  const percentLabel = `${precisePercent(progress.percent, readerType, locale)}%`;
  const positionLabel = readerType === 'reflowable'
    ? (currentNavigationLabel ?? locationLabel ?? progress.position)
    : progressPageLabel(progress);
  const remainingSectionSeconds = secondsValue(progressExtra.remainingSectionSeconds);
  const remainingLabel = readerType === 'reflowable'
    ? (remainingSectionSeconds === null ? null : remainingTimeLabel(remainingSectionSeconds, locale))
    : (progress.total === null
      ? null
      : locale === 'zh-CN'
        ? `剩余 ${Math.max(0, progress.total - progress.page)} 页`
        : `${Math.max(0, progress.total - progress.page)} pages left`);
  const selectedProgressLabel = settings.progressStyle === 'hidden'
    ? null
    : settings.progressStyle === 'percent'
      ? percentLabel
      : settings.progressStyle === 'position'
        ? positionLabel
        : settings.progressStyle === 'remaining'
          ? (remainingLabel ?? positionLabel)
          : readerType === 'reflowable'
            ? (remainingLabel ?? percentLabel)
            : positionLabel;
  const clockLabel = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(clockTime);
  const progressDetail = [currentNavigationLabel, locationLabel, selectedProgressLabel].filter(Boolean).join(' · ');
  const readerDirection: ComicDirection = readingDirection ?? (readerType === 'comic' ? settings.comicDirection : 'ltr');
  const leftDirection = readerPhysicalHorizontalPageTurn('left', readerDirection);
  const rightDirection = readerPhysicalHorizontalPageTurn('right', readerDirection);
  const leftChapter = leftDirection === 'previous' ? previousChapter : nextChapter;
  const rightChapter = rightDirection === 'previous' ? previousChapter : nextChapter;
  const chapterLabels = readerType === 'reflowable';
  const previousChapterLabel = chapterLabels ? '上一章' : '上一页';
  const nextChapterLabel = chapterLabels ? '下一章' : '下一页';
  const leftChapterLabel = leftDirection === 'previous' ? previousChapterLabel : nextChapterLabel;
  const rightChapterLabel = rightDirection === 'previous' ? previousChapterLabel : nextChapterLabel;
  const zoomedPannable = readerType === 'pdf'
    ? settings.pdfZoom > 1
    : readerType === 'comic' && settings.comicZoom > 1;
  const usesCompactPassiveProgress = readerType === 'reflowable' || readerType === 'comic';
  const passiveProgressAreaHeight = usesCompactPassiveProgress ? 'calc(2.75rem + var(--shuku-safe-area-bottom))' : readerBottomAreaHeight;
  const supportsTextAnnotations = readerType !== 'comic';
  const accentColor = themeSurface.accent;
  const pageWidth = readerType === 'reflowable'
    ? settings.pageWidth
    : readerType === 'comic'
      ? settings.comicPageWidth
      : settings.pdfPageWidth;
  const pageWidthMaximum = readerPageWidthSliderMaximum(readerViewportWidth);
  const mobilePageWidth = readerViewportWidth <= MOBILE_READER_VIEWPORT_MAXIMUM;
  panelRef.current = panel;
  interactionBlockedRef.current = interactionBlocked;
  capabilitiesRef.current = capabilities;
  settingsRef.current = settings;

  useEffect(() => {
    const viewport = readerViewportRef.current;
    if (!viewport) return;
    const measure = () => setReaderViewportWidth(Math.max(1, Math.round(viewport.getBoundingClientRect().width)));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!settings.showClock) return;
    const updateClock = () => setClockTime(new Date());
    updateClock();
    const delay = 60_000 - (Date.now() % 60_000);
    let intervalId: number | null = null;
    const timeoutId = window.setTimeout(() => {
      updateClock();
      intervalId = window.setInterval(updateClock, 60_000);
    }, delay);
    return () => {
      window.clearTimeout(timeoutId);
      if (intervalId !== null) window.clearInterval(intervalId);
    };
  }, [settings.showClock]);

  useEffect(() => {
    if (!settings.keepScreenAwake || !wakeLockPort) return;
    const controller = createScreenWakeLockController(document, wakeLockPort);
    controller.start();
    return () => controller.stop();
  }, [settings.keepScreenAwake, wakeLockPort]);

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
    const closingPanel = panelRef.current;
    setPanel(null);
    window.requestAnimationFrame(() => {
      if (panelReturnFocusRef.current?.isConnected) {
        panelReturnFocusRef.current.focus();
        return;
      }
      if (!closingPanel) return;
      const matchingTriggers = Array.from(document.querySelectorAll<HTMLElement>(
        `[data-reader-controller="bottom-console"] [data-reader-panel-trigger="${closingPanel}"]`
      ));
      matchingTriggers.find((trigger) => trigger.getClientRects().length > 0)?.focus();
    });
  }

  function dismissPanelWithoutFocusRestore() {
    if (!panelRef.current) return;
    setPanel(null);
  }

  function togglePanel(next: ReaderPanel, returnFocus: HTMLElement) {
    if (!returnFocus.closest('[data-reader-workspace="true"]')) {
      panelReturnFocusRef.current = returnFocus;
    }
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
    if (intent === 'next') return goNext();
    return goPrev();
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
    else if (intent === 'first') return jumpToStart();
    else if (intent === 'last') return jumpToEnd();
    else return goByIntent(intent);
  }
  handleInputIntentRef.current = handleInputIntent;

  function handleReaderTap(clientX: number, clientY: number) {
    const bounds = readerViewportRef.current?.getBoundingClientRect();
    if (!bounds) return;
    void handleInputIntent(readerPointerIntentInViewport(clientX, clientY, bounds, readerDirectionRef.current, settingsRef.current.tapZones));
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
    const keyboardNavigation = keyboardNavigationRef.current;
    function onKeyDown(event: KeyboardEvent) {
      const intent = readerKeyIntent(event, readerDirectionRef.current, {
        keyboardPageTurn: settingsRef.current.keyboardPageTurn,
        volumeKeyPageTurn: settingsRef.current.volumeKeyPageTurn
      });
      if (!intent) return;
      if (intent === 'escape') {
        event.preventDefault();
        handleInputIntentRef.current(intent);
        return;
      }
      if (
        isInteractionBlocked()
        || isReaderKeyboardControlTarget(event.target, event.key)
        || hasActiveTextSelection(window.getSelection())
      ) return;
      event.preventDefault();
      keyboardNavigation.keyDown(event, () => handleInputIntentRef.current(intent));
    }

    function onKeyUp(event: KeyboardEvent) {
      keyboardNavigation.keyUp(event);
    }

    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
      keyboardNavigation.reset();
    };
  }, []);

  useEffect(() => {
    if (!panel) return;
    setControlsVisibility(true);
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
    const focusables = () => Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector))
      .filter((element) => !element.hidden && element.getClientRects().length > 0);
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

  async function navigateToItem(item: ReaderNavigationItem, dismissPanel: boolean) {
    if (currentNavigationItem && navigationItemKey(item) === navigationItemKey(currentNavigationItem)) {
      if (dismissPanel) closePanel();
      keepControlsOpen();
      return;
    }
    const activeControls = controlsRef.current;
    let accepted = false;
    if (readerType === 'reflowable' && !item.href) {
      accepted = false;
    } else if (readerType === 'reflowable' && item.href && capabilitiesRef.current?.canJumpToHref !== false && activeControls?.jumpToHref) {
      accepted = await activeControls.jumpToHref(item.href);
    } else if (capabilitiesRef.current?.canJumpToIndex !== false && activeControls?.jumpToIndex) {
      accepted = await activeControls.jumpToIndex(item.index);
    }
    if (dismissPanel && accepted) closePanel();
    keepControlsOpen();
  }

  async function jumpToItem(item: ReaderNavigationItem) {
    await navigateToItem(item, true);
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
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 z-[120]"
        data-reader-top-safe-area="true"
        style={{
          backgroundColor: themeSurface.background,
          height: 'var(--shuku-safe-area-top)'
        }}
      />
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
        const swipeIntent = settings.swipePageTurn && horizontalPaging === 'shell-discrete' && !zoomedPannable
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
          className={cn('shuku-reader-control-border pointer-events-auto relative mx-auto flex h-12 w-full max-w-5xl items-center justify-between rounded-full border px-1 shadow-sm backdrop-blur-xl', dark ? 'bg-slate-950/75' : 'bg-white/80')}
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
          <span className="pointer-events-none absolute inset-x-12 truncate px-2 text-center text-sm font-medium md:hidden">
            {currentNavigationLabel ?? progressPageLabel(progress)}
          </span>
          <button
            type="button"
            disabled={!canBookmark || !onToggleBookmark}
            onClick={() => toggleBookmark()}
            className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition active:scale-[0.97] disabled:opacity-40', dark ? 'hover:bg-white/10' : 'hover:bg-stone-900/5', bookmarkActive ? 'shuku-reader-accent-text' : '')}
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
          {selectedProgressLabel || settings.showClock ? (
            <div className="flex items-center justify-between gap-3 text-[11px] opacity-60 md:text-xs">
              <span className="truncate">{selectedProgressLabel}</span>
              {settings.showClock ? <time className="shrink-0 tabular-nums">{clockLabel}</time> : null}
            </div>
          ) : null}
          <div className="min-h-0 flex-1" aria-hidden="true" />
        </div>
      </div>

      <div
        className={cn(
          'shuku-reader-bottom-bleed shuku-reader-bottom-console pointer-events-none absolute inset-x-0 px-3 pt-2 md:px-5',
          panel ? 'z-40' : 'z-20',
          dark ? 'text-slate-100' : 'text-stone-900'
        )}
        style={{
          paddingBottom: 'calc(0.75rem + var(--shuku-safe-area-bottom))',
          transform: controlsVisible ? 'translateY(0)' : 'translateY(100%)',
          opacity: controlsVisible ? 1 : 0
        }}
        data-reader-control="true"
        data-reader-controller="bottom-console"
        data-reader-panel-state={panel ?? 'home'}
        aria-hidden={!controlsVisible}
        {...inertWhen(!controlsVisible)}
        onClick={stopControlEvent}
      >
        <div
          ref={panelElementRef}
          role={panel ? 'dialog' : undefined}
          aria-modal={panel ? 'true' : undefined}
          aria-labelledby={panel ? 'reader-panel-title' : undefined}
          tabIndex={panel ? -1 : undefined}
          className={cn('shuku-reader-console-surface shuku-reader-control-border pointer-events-auto relative mx-auto flex h-full flex-col overflow-hidden rounded-[1.65rem] border shadow-[0_8px_28px_rgba(75,54,31,0.10)] md:rounded-[1.35rem]', readerBottomControlsMaxWidth)}
          style={{ '--shuku-reader-surface': themeSurface.background, backgroundColor: themeSurface.background } as CSSProperties}
          data-reader-console-surface="true"
          data-reader-panel={panel ?? undefined}
          data-reader-workspace={panel ? 'true' : undefined}
          id={panel ? 'reader-panel' : undefined}
        >
          {panel ? (
            <div
              key={panel}
              className="shuku-reader-control-workspace shuku-reader-panel-surface flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden overscroll-contain p-4 md:p-5"
              data-reader-panel-surface="true"
              style={{
                paddingLeft: 'calc(1rem + var(--shuku-safe-area-left))',
                paddingRight: 'calc(1rem + var(--shuku-safe-area-right))'
              }}
              onClick={stopControlEvent}
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div id="reader-panel-title" className="text-sm font-semibold">
                    {panel === 'toc'
                      ? i18nAttribute("目录")
                      : panel === 'notes'
                        ? i18nAttribute("笔记")
                        : panel === 'bookmarks'
                          ? i18nAttribute("书签")
                          : panel === 'appearance'
                            ? i18nAttribute("外观")
                            : panel === 'settings'
                              ? i18nAttribute("设置")
                              : i18nAttribute("标注与批注")}
                  </div>
                  {panel === 'settings' || panel === 'appearance' ? null : (
                    <div className="mt-0.5 text-xs opacity-60">
                      {panel === 'bookmarks' || panel === 'notes' ? i18nAttribute("{value0} 个书签", { value0: orderedBookmarks.length }) : progressDetail}
                    </div>
                  )}
                </div>
                <button type="button" onClick={() => { closePanel(); keepControlsOpen(); }} className="flex h-11 w-11 items-center justify-center rounded-full transition active:scale-[0.98] hover:bg-white/10" aria-label={i18nAttribute("关闭面板")}>
                  <X size={18} />
                </button>
              </div>

              {panel === 'toc' && resourceNavigation ? (
                <ResourceNavigationPanel
                  navigation={resourceNavigation}
                  readerType={readerType}
                  activeItemKey={currentNavigationItem ? navigationItemKey(currentNavigationItem) : null}
                  dark={dark}
                  onJumpItem={(item) => {
                    void jumpToItem(item);
                  }}
                />
              ) : null}

              {panel === 'toc' && !resourceNavigation ? (
                <div data-pwa-scroll="true" className="mt-5 min-h-0 flex-1 overflow-auto overscroll-contain pr-1">
                  {navItems.length === 0 ? <div className="py-6 text-sm opacity-60"><I18nText>暂无可跳转条目</I18nText></div> : null}
                  <div className="space-y-1">
                    {navItems.map((item, itemIndex) => (
                      <button
                        key={`${item.index}-${item.title}`}
                        type="button"
                        aria-current={currentNavigationItem && navigationItemKey(item) === navigationItemKey(currentNavigationItem) ? 'location' : undefined}
                        onClick={() => { void jumpToItem(item); }}
                        className={cn('flex min-h-11 w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left text-sm transition active:scale-[0.99]', currentNavigationItem && navigationItemKey(item) === navigationItemKey(currentNavigationItem) ? 'shuku-reader-accent-solid' : dark ? 'shuku-reader-control-border bg-white/[0.04] hover:bg-white/10' : 'shuku-reader-control-border bg-white/55 hover:bg-white/80')}
                      >
                        <span className="w-9 shrink-0 tabular-nums opacity-60">{itemIndex + 1}</span>
                        <span className="line-clamp-2">{item.title}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              {panel === 'notes' && supportsTextAnnotations ? (
                <ReaderSegmentedControl
                  ariaLabel={i18nAttribute("笔记")}
                  value={notesTab}
                  options={[
                    { value: 'bookmarks', label: i18nAttribute("书签") },
                    { value: 'annotations', label: i18nAttribute("标注") }
                  ]}
                  onChange={setNotesTab}
                  dark={dark}
                  behavior="tabs"
                  className="mt-4"
                />
              ) : null}

              {panel === 'bookmarks' || (panel === 'notes' && notesTab === 'bookmarks') ? (
                <div className="mt-3 flex min-h-0 flex-1 flex-col">
                  <button
                    type="button"
                    disabled={!canBookmark || !onToggleBookmark}
                    onClick={() => toggleBookmark(false)}
                    className={cn(
                      'flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-xl border px-3 text-sm font-medium transition active:scale-[0.98] disabled:opacity-40',
                      bookmarkActive
                        ? 'shuku-reader-accent-selected border-current/20'
                        : dark ? 'shuku-reader-control-border hover:bg-white/10' : 'shuku-reader-control-border hover:bg-stone-900/5'
                    )}
                    aria-label={bookmarkActive ? i18nAttribute("移除当前位置书签") : i18nAttribute("添加当前位置书签")}
                  >
                    <Bookmark size={16} fill={bookmarkActive ? 'currentColor' : 'none'} />
                    {bookmarkActive ? i18nAttribute("移除当前位置") : i18nAttribute("添加当前位置")}
                  </button>
                  <div data-pwa-scroll="true" className="mt-3 min-h-0 flex-1 overflow-auto overscroll-contain pr-1">
                    {orderedBookmarks.length === 0 ? (
                      <div className={cn('shuku-reader-control-border flex h-full min-h-40 flex-col items-center justify-center rounded-2xl border px-5 text-center', dark ? 'bg-white/[0.035]' : 'bg-white/45')}>
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
                            <div key={bookmark.id} className={cn('flex min-h-12 items-stretch rounded-xl transition', active ? 'shuku-reader-accent-selected' : dark ? 'bg-white/[0.06]' : 'bg-stone-900/[0.04]')}>
                              <button
                                type="button"
                                onClick={() => { void jumpToBookmark(bookmark); }}
                                className="min-w-0 flex-1 px-3 py-2.5 text-left active:scale-[0.99]"
                                aria-label={i18nAttribute("跳转到书签：{value0}", { value0: bookmark.label })}
                              >
                                <span className="block truncate text-sm font-medium">{i18nAttribute(bookmark.label)}</span>
                                <span className="mt-0.5 flex items-center gap-2 text-[11px] opacity-55">
                                  <span className="tabular-nums">{clampPercent(bookmark.position.presentation.displayPercent)}%</span>
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

              {panel === 'annotations' || (panel === 'notes' && notesTab === 'annotations') ? (
                <div className="mt-5 min-h-0 flex-1">
                  <ReaderSegmentedControl
                    ariaLabel={i18nAttribute("标注分类")}
                    value={annotationTab}
                    options={[
                      { value: 'book', label: i18nAttribute("书内注释") },
                      { value: 'mine', label: i18nAttribute("我的标注") }
                    ]}
                    onChange={setAnnotationTab}
                    dark={dark}
                    behavior="tabs"
                  />
                  <div role="tabpanel" data-pwa-scroll="true" className="shuku-reader-control-border mt-4 min-h-0 overflow-auto rounded-2xl border p-5 text-center">
                    <Highlighter className="mx-auto opacity-45" size={24} />
                    <div className="mt-3 text-sm font-medium">{annotationTab === 'book' ? i18nAttribute("暂无可展示的书内注释") : i18nAttribute("还没有划线或批注")}</div>
                    <p className="mx-auto mt-2 max-w-xs text-xs leading-5 opacity-60">
                      {annotationTab === 'book'
                        ? i18nAttribute("当前资源尚未建立注释索引；后续接入 EPUB 脚注与尾注解析后会集中显示在这里。")
                        : i18nAttribute("划线、批注与跨设备同步的数据层尚未接入；这里先保留统一入口与完整的响应式结构。")}
                    </p>
                  </div>
                </div>
              ) : null}

              {panel === 'appearance' || panel === 'settings' ? (
                <ReaderPreferencesPanel panel={panel} settings={settings} readerType={readerType} dark={dark}
                  updateSettings={updateSettings} onResetSettings={onResetSettings} keepControlsOpen={keepControlsOpen}
                  pageWidthMaximum={pageWidthMaximum} mobilePageWidth={mobilePageWidth} wakeLockSupported={wakeLockSupported}
                  canZoom={capabilities?.canZoom !== false} supportedControls={capabilities?.supportedControls} />
              ) : null}

            </div>
          ) : null}

          <div className="shuku-reader-console-home shuku-reader-console-bar flex min-w-0 shrink-0" data-reader-console-controls="true">
          <div className="flex min-w-0 flex-1 flex-col md:hidden">
            <div data-reader-mobile-progress-controls="true" className="px-2 pb-1 pt-2">
              <div className="flex min-w-0 items-center gap-1">
                <button
                  type="button"
                  aria-label={i18nAttribute(leftChapterLabel)}
                  data-reader-chapter-target={leftChapter?.href ?? leftChapter?.index}
                  disabled={!leftChapter}
                  onClick={() => { if (leftChapter) void navigateToItem(leftChapter, false); }}
                  className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition active:scale-[0.97] disabled:opacity-35', dark ? 'hover:bg-white/10' : 'hover:bg-stone-900/5')}
                >
                  <ChevronLeft size={20} />
                </button>
              <input
                aria-label={i18nAttribute("阅读进度")}
                type="range"
                min={0}
                max={100}
                step={0.1}
                value={progressScrubPercent ?? clampPercent(progress.percent)}
                disabled={!controls || capabilities?.canJumpToProgress === false}
                onChange={(event) => {
                  void jumpToPercent(Number(event.target.value), true);
                  keepControlsOpen();
                }}
                onBlur={flushPendingProgressJump}
                className="h-7 min-w-0 flex-1 cursor-pointer disabled:cursor-not-allowed"
                style={{ accentColor }}
              />
                <button
                  type="button"
                  aria-label={i18nAttribute(rightChapterLabel)}
                  data-reader-chapter-target={rightChapter?.href ?? rightChapter?.index}
                  disabled={!rightChapter}
                  onClick={() => { if (rightChapter) void navigateToItem(rightChapter, false); }}
                  className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition active:scale-[0.97] disabled:opacity-35', dark ? 'hover:bg-white/10' : 'hover:bg-stone-900/5')}
                >
                  <ChevronRight size={20} />
                </button>
              </div>
            </div>

            <div data-reader-console-nav="true" className="shuku-reader-control-border grid min-h-[4.75rem] grid-cols-4 border-t px-2 py-1">
              <ReaderControlNavButton icon={ListTree} label={i18nAttribute("目录")} selected={panel === 'toc'} expanded={panel === 'toc'} panelTrigger="toc" onClick={(event) => togglePanel('toc', event.currentTarget)} dark={dark} />
              <ReaderControlNavButton
                icon={NotebookPen}
                label={i18nAttribute("笔记")}
                active={bookmarkActive}
                selected={panel === 'notes'}
                expanded={panel === 'notes'}
                panelTrigger="notes"
                onClick={(event) => {
                  setNotesTab('bookmarks');
                  togglePanel('notes', event.currentTarget);
                }}
                dark={dark}
              />
              <ReaderControlNavButton icon={Palette} label={i18nAttribute("外观")} selected={panel === 'appearance'} expanded={panel === 'appearance'} panelTrigger="appearance" onClick={(event) => togglePanel('appearance', event.currentTarget)} dark={dark} />
              <ReaderControlNavButton icon={Settings} label={i18nAttribute("设置")} ariaLabel={i18nAttribute("阅读设置")} selected={panel === 'settings'} expanded={panel === 'settings'} panelTrigger="settings" onClick={(event) => togglePanel('settings', event.currentTarget)} dark={dark} />
            </div>
          </div>

          <div className="hidden h-full w-full items-stretch md:flex">
            {readerType !== 'reflowable' || navItems.length > 0 || resourceNavigation ? (
              <ReaderControlNavButton layout="dock" icon={ListTree} label={i18nAttribute("目录")} selected={panel === 'toc'} expanded={panel === 'toc'} panelTrigger="toc" onClick={(event) => togglePanel('toc', event.currentTarget)} dark={dark} />
            ) : null}
            <ReaderControlNavButton layout="dock" icon={NotebookPen} label={i18nAttribute("笔记")} active={bookmarkActive} selected={panel === 'notes'} expanded={panel === 'notes'} panelTrigger="notes" onClick={(event) => { setNotesTab('bookmarks'); togglePanel('notes', event.currentTarget); }} dark={dark} />
            <div className="min-w-0 flex-1 items-center gap-2 px-2 md:flex lg:px-4">
            <button type="button" aria-label={i18nAttribute(leftChapterLabel)} data-reader-chapter-target={leftChapter?.href ?? leftChapter?.index} disabled={!leftChapter} onClick={() => { if (leftChapter) void navigateToItem(leftChapter, false); }} className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition active:scale-[0.97] disabled:opacity-35', dark ? 'hover:bg-white/10' : 'hover:bg-stone-900/5')}>
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
                step={0.1}
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
            <button type="button" aria-label={i18nAttribute(rightChapterLabel)} data-reader-chapter-target={rightChapter?.href ?? rightChapter?.index} disabled={!rightChapter} onClick={() => { if (rightChapter) void navigateToItem(rightChapter, false); }} className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition active:scale-[0.97] disabled:opacity-35', dark ? 'hover:bg-white/10' : 'hover:bg-stone-900/5')}>
              <ChevronRight size={20} />
            </button>
            </div>
            <ReaderControlNavButton layout="dock" icon={Palette} label={i18nAttribute("外观")} selected={panel === 'appearance'} expanded={panel === 'appearance'} panelTrigger="appearance" onClick={(event) => togglePanel('appearance', event.currentTarget)} dark={dark} />
            <ReaderControlNavButton layout="dock" icon={Settings} label={i18nAttribute("设置")} ariaLabel={i18nAttribute("阅读设置")} selected={panel === 'settings'} expanded={panel === 'settings'} panelTrigger="settings" onClick={(event) => togglePanel('settings', event.currentTarget)} dark={dark} />
          </div>
            </div>

      {bookmarkNotice ? (
        <div role="status" className={cn('shuku-reader-control-border pointer-events-none absolute inset-x-0 z-30 mx-auto w-fit rounded-full border px-4 py-2 text-xs font-medium shadow-lg backdrop-blur-xl', dark ? 'bg-slate-950/90' : 'bg-white/90')} style={{ bottom: 'calc(6rem + var(--shuku-safe-area-bottom))' }}>
          {bookmarkNotice}
        </div>
      ) : null}

        </div>
      </div>
      </div>
    </div>
  );
}

function ThemeSwatches({ value, onChange, dark }: { value: ReaderTheme; onChange: (value: ReaderTheme) => void; dark: boolean }) {
  const { t: i18nAttribute } = useAttributeI18n();
  return (
    <div role="group" aria-label={i18nAttribute("主题")} className={cn('shuku-reader-control-border flex items-center justify-center gap-3 rounded-2xl border p-1.5', dark ? 'bg-white/[0.06]' : 'bg-stone-900/[0.055]')}>
      {READER_SETTINGS_CATALOG.optionGroups.READER_THEME_OPTIONS.map((option) => {
        const selected = value === option.value;
        const surface = readerThemeSurfaces[option.value];
        return (
          <button
            key={option.value}
            type="button"
            aria-label={i18nAttribute(option.label['zh-CN'])}
            aria-pressed={selected}
            onClick={() => onChange(option.value)}
            className={cn('flex h-11 w-11 items-center justify-center rounded-full border-2 border-transparent p-1 transition active:scale-[0.96]', selected ? '' : 'hover:border-[var(--shuku-reader-control-border)]')}
            style={selected ? { borderColor: surface.accent } : undefined}
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

function CompactSettingOptions({ label, value, options, onChange, dark, disabled = false, disambiguateLabels = false, description }: {
  label: string;
  value: string;
  options: ReadonlyArray<{ value: string; label: string; icon?: LucideIcon; disabled?: boolean }>;
  onChange: (value: string) => void;
  dark: boolean;
  disabled?: boolean;
  disambiguateLabels?: boolean;
  description?: string;
}) {
  const { t: i18nAttribute } = useAttributeI18n();
  const descriptionId = useId();
  return (
    <div className={cn('space-y-1', disabled && 'opacity-45')}>
      <div className="flex items-center gap-3">
        <span className="w-9 shrink-0 text-xs font-medium opacity-55">{i18nAttribute(label)}</span>
        <ReaderSegmentedControl
          ariaLabel={i18nAttribute(label)}
          ariaDescribedBy={description ? descriptionId : undefined}
          value={value}
          options={options.map((option) => ({
            ...option,
            label: i18nAttribute(option.label),
            ariaLabel: i18nAttribute(disambiguateLabels ? `${label}${option.label}` : option.label)
          }))}
          onChange={onChange}
          dark={dark}
          disabled={disabled}
          className={cn('flex-1', options.length <= 3 && 'min-[900px]:max-w-[32rem]')}
        />
      </div>
      {!options.some((option) => option.value === value) ? <p className="pl-12 text-xs">{value}</p> : null}
      {description ? <p id={descriptionId} className="pl-12 text-[11px] leading-4 opacity-55">{description}</p> : null}
    </div>
  );
}

function CompactStepper({ label, value, onMinus, onPlus, dark, disabled = false }: { label: string; value: string; onMinus: () => void; onPlus: () => void; dark: boolean; disabled?: boolean }) {
  const { t: i18nAttribute } = useAttributeI18n();
  return (
    <div className="flex items-center gap-3 min-[900px]:max-w-[32rem]">
      <span className="w-9 shrink-0 text-xs font-medium opacity-55">{i18nAttribute(label)}</span>
      <div className={cn('shuku-reader-control-border flex min-w-0 flex-1 items-center rounded-xl border p-1', dark ? 'bg-white/[0.07]' : 'bg-stone-900/[0.055]')}>
        <button type="button" disabled={disabled} onClick={onMinus} className={cn('flex h-9 w-9 items-center justify-center rounded-lg transition active:scale-[0.97]', dark ? 'hover:bg-white/10' : 'hover:bg-white/60')} aria-label={i18nAttribute("{value0}减少", { value0: label })}>
          <Minus size={14} />
        </button>
        <span className="min-w-14 flex-1 text-center text-xs tabular-nums">{value}</span>
        <button type="button" disabled={disabled} onClick={onPlus} className={cn('flex h-9 w-9 items-center justify-center rounded-lg transition active:scale-[0.97]', dark ? 'hover:bg-white/10' : 'hover:bg-white/60')} aria-label={i18nAttribute("{value0}增加", { value0: label })}>
          <Plus size={14} />
        </button>
      </div>
    </div>
  );
}

function CompactRangeSetting({ label, value, minimum, maximum, step, suffix, disabled, description, onChange, dark }: {
  label: string;
  value: number;
  minimum: number;
  maximum: number;
  step: number;
  suffix: string;
  disabled: boolean;
  description?: string;
  onChange: (value: number) => void;
  dark: boolean;
}) {
  return (
    <div className={cn('min-[900px]:max-w-[32rem]', disabled && 'opacity-55')}>
      <div className="flex items-center gap-3">
        <span className="w-9 shrink-0 text-xs font-medium opacity-55">{label}</span>
        <label className={cn('shuku-reader-control-border flex min-w-0 flex-1 items-center gap-3 rounded-xl border px-3', dark ? 'bg-white/[0.07]' : 'bg-stone-900/[0.055]')}>
          <input
            aria-label={label}
            type="range"
            min={minimum}
            max={maximum}
            step={step}
            value={value}
            disabled={disabled}
            onChange={(event) => onChange(Number(event.target.value))}
            className="h-11 min-w-0 flex-1 cursor-pointer disabled:cursor-not-allowed"
          />
          <span className="w-14 shrink-0 text-right text-xs tabular-nums">{value}{suffix}</span>
        </label>
      </div>
      {description ? <p className="ml-12 mt-1 text-[11px] leading-4 opacity-55">{description}</p> : null}
    </div>
  );
}

function ReaderSettingsSection({ icon: Icon, title, dark, nested = false, children }: {
  icon: LucideIcon;
  title: string;
  dark: boolean;
  nested?: boolean;
  children: ReactNode;
}) {
  return (
    <section className={cn(
      'shuku-reader-control-border rounded-2xl border p-3',
      nested ? 'bg-transparent' : dark ? 'bg-white/[0.035]' : 'bg-white/45'
    )}>
      <div className="mb-3 flex items-center gap-2 px-1 text-xs font-semibold">
        <Icon size={16} className="opacity-65" />
        <span>{title}</span>
      </div>
      <div className="space-y-2.5">{children}</div>
    </section>
  );
}

function ReaderToggleRow({ label, description, checked, disabled = false, onChange, dark }: {
  label: string;
  description?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
  dark: boolean;
}) {
  const descriptionId = useId();
  return (
    <label className={cn('shuku-reader-control-border flex min-h-11 items-center gap-3 rounded-xl border px-3 py-2', disabled && 'opacity-45', dark ? 'bg-white/[0.045]' : 'bg-white/55')}>
      <span className="min-w-0 flex-1">
        <span className="block text-xs font-medium">{label}</span>
        {description ? <span id={descriptionId} className="mt-0.5 block text-[11px] leading-4 opacity-55">{description}</span> : null}
      </span>
      <input type="checkbox" className="peer sr-only" checked={checked} disabled={disabled} aria-describedby={description ? descriptionId : undefined} onChange={(event) => onChange(event.target.checked)} />
      <span data-reader-toggle-control="true" aria-hidden="true" className={cn('relative h-6 w-11 shrink-0 rounded-full border transition-colors peer-focus-visible:ring-2', checked ? 'shuku-reader-accent-toggle' : dark ? 'shuku-reader-control-border bg-white/10' : 'shuku-reader-control-border bg-stone-900/10')}>
        <span data-reader-toggle-knob="true" className={cn('absolute left-0.5 top-1/2 h-5 w-5 -translate-y-1/2 rounded-full bg-white shadow-sm transition-transform', checked && 'translate-x-5')} />
      </span>
    </label>
  );
}

function ResourceNavigationPanel({ navigation, readerType, activeItemKey, dark, onJumpItem }: { navigation: ReaderResourceNavigation; readerType: ReaderKind; activeItemKey: string | null; dark: boolean; onJumpItem: (item: ReaderNavigationItem) => void }) {
  const { t: i18nAttribute } = useAttributeI18n();
  const showResources = navigation.resourceSections.length > 1;
  const idleText = navigation.loading ? '正在切换...' : null;
  const isComic = readerType === 'comic';

  return (
    <div data-pwa-scroll="true" className="mt-5 min-h-0 flex-1 overflow-auto overscroll-contain pr-1">
      {idleText ? <div className="mb-3 rounded-xl bg-white/10 px-3 py-2 text-xs opacity-70">{idleText}</div> : null}
      {showResources && !isComic ? (
        <ResourceNavigationGroup title={i18nAttribute("资源")}>
          <ResourceSelect
            items={navigation.resourceSections.map((resource, index) => ({
              id: resource.id,
              title: resource.title || (isComic
                ? i18nAttribute("第 {value0} 话", { value0: index + 1 })
                : i18nAttribute("第 {value0} 资源", { value0: index + 1 }))
            }))}
            value={navigation.currentResourceId}
            onChange={navigation.onSelectResource}
            disabled={navigation.loading}
            dark={dark}
            className="w-full"
          />
        </ResourceNavigationGroup>
      ) : null}

      {showResources && isComic ? (
        <ResourceNavigationGroup title={isComic ? i18nAttribute("资源/话") : i18nAttribute("资源")}>
          {navigation.resourceSections.map((resource, index) => (
            <button
              key={resource.id}
              type="button"
              disabled={navigation.loading}
              onClick={() => navigation.onSelectResource(resource.id)}
              className={comicNavButtonClass(resource.id === navigation.currentResourceId, dark)}
            >
              <span className="w-8 shrink-0 tabular-nums opacity-60">{index + 1}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{resource.title || (isComic
                  ? i18nAttribute("第 {value0} 话", { value0: index + 1 })
                  : i18nAttribute("第 {value0} 资源", { value0: index + 1 }))}</span>
                <span className="mt-0.5 block truncate text-xs opacity-65">{resource.pageCount || 0} {isComic ? i18nAttribute("页") : i18nAttribute("章")}</span>
              </span>
            </button>
          ))}
        </ResourceNavigationGroup>
      ) : null}

      <ResourceNavigationGroup title={isComic ? (showResources ? i18nAttribute("当前资源页码") : i18nAttribute("页码")) : (showResources ? i18nAttribute("当前资源章节") : i18nAttribute("章节"))}>
        {navigation.pages.length === 0 ? <div className="py-6 text-sm opacity-60">{isComic ? i18nAttribute("暂无可跳转页码") : i18nAttribute("暂无可跳转章节")}</div> : null}
        <div className={isComic ? 'grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-3' : 'space-y-1'}>
          {navigation.pages.map((item, itemIndex) => (
            <button
              key={`${item.index}-${item.title}`}
              type="button"
              aria-current={activeItemKey && navigationItemKey(item) === activeItemKey ? 'location' : undefined}
              disabled={navigation.loading}
              onClick={() => onJumpItem(item)}
              className={cn(
                isComic ? 'min-h-11 rounded-xl px-2 text-sm tabular-nums transition active:scale-[0.98] disabled:cursor-wait disabled:opacity-60' : 'flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition active:scale-[0.99] disabled:cursor-wait disabled:opacity-60',
                activeItemKey && navigationItemKey(item) === activeItemKey ? 'shuku-reader-accent-solid' : dark ? 'shuku-reader-control-border border bg-white/[0.05] hover:bg-white/10' : 'shuku-reader-control-border border bg-white/55 hover:bg-white/80'
              )}
            >
              {isComic ? item.index : (
                <>
                  <span className="w-9 shrink-0 tabular-nums opacity-60">{itemIndex + 1}</span>
                  <span className="line-clamp-2">{item.title}</span>
                </>
              )}
            </button>
          ))}
        </div>
      </ResourceNavigationGroup>
    </div>
  );
}

function ResourceNavigationGroup({ title, children }: { title: string; children: ReactNode }) {
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
    selected ? 'shuku-reader-accent-solid' : dark ? 'hover:bg-white/10' : 'hover:bg-stone-100'
  );
}

function ReaderPreferencesPanel({ panel, settings, readerType, dark, updateSettings, onResetSettings, keepControlsOpen, pageWidthMaximum, mobilePageWidth, wakeLockSupported, canZoom, supportedControls: adapterSupportedControls }: {
  panel: 'appearance' | 'settings'; settings: ReaderSettings; readerType: ReaderKind; dark: boolean;
  updateSettings: (value: Partial<ReaderSettings>) => void;
  onResetSettings?: () => void | Promise<void>; keepControlsOpen: () => void;
  pageWidthMaximum: number; mobilePageWidth: boolean; wakeLockSupported: boolean; canZoom: boolean; supportedControls?: readonly string[];
}) {
  const { t } = useAttributeI18n();
  const [advanced, setAdvanced] = useState(false);
  const preferences = readerSettingsToPreferences(settings);
  const sections = READER_SETTINGS_CATALOG.sections.filter((section) => section.panel === panel);
  function update(id: ReaderSettingId, value: string) {
    if (id === 'theme') {
      const next = changeReaderSetting(preferences, id, value);
      updateSettings({ theme: next.appearance.theme, themeMode: 'manual' });
    } else if (id === 'themeMode') {
      updateSettings({ themeMode: value === 'system' ? 'system' : 'manual', theme: value === 'system' ? settings.theme : settings.manualTheme });
    } else {
      updateSettings(preferencesToReaderSettings(changeReaderSetting(preferences, id, value)));
    }
  }
  function control(setting: typeof READER_SETTINGS_CATALOG.settings[number]) {
    const id = setting.id;
    const label = t(setting.label['zh-CN']);
    const saved = readerSettingValue(preferences, id);
    const pageWidth = id === 'textPageWidth' || id === 'comicPageWidth' || id === 'pdfPageWidth';
    const zoom = id === 'comicZoom' || id === 'pdfZoom';
    const supportedControls = new Set<string>(adapterSupportedControls ?? READER_SETTINGS_CATALOG.settings.flatMap((candidate) => candidate.control ? [candidate.control] : []));
    supportedControls.delete('VolumeKeys');
    const state = readerSettingAvailability(id, {
      morphology: readerType,
      ready: true,
      supportedControls,
      wideViewport: !mobilePageWidth,
      wakeLockSupported,
      canZoom,
      preferences
    });
    const disabled = state.availability !== 'available';
    const description = state.reason
      ? t(READER_SETTINGS_CATALOG.availabilityReasons[state.reason]['zh-CN'])
      : undefined;
    if (id === 'theme') return <ThemeSwatches key={id} value={settings.theme} onChange={(value) => update(id, value)} dark={dark} />;
    if (setting.kind === 'action') return onResetSettings ? <button key={id} type="button" onClick={() => { void onResetSettings(); keepControlsOpen(); }} className="min-h-11 w-full" aria-label={label}>{label}</button> : null;
    if (setting.kind === 'toggle') {
      const fixedSwipe = id === 'swipePageTurn' && readerType === 'reflowable';
      const checked = fixedSwipe || saved === 'true' || saved === 'system';
      return <ReaderToggleRow key={id} label={label} description={description} checked={checked} disabled={disabled} onChange={(value) => update(id, id === 'themeMode' ? value ? 'system' : 'manual' : String(value))} dark={dark} />;
    }
    if (setting.kind === 'number' && setting.limits) {
      const [minimum, maximum, step] = setting.limits;
      if (pageWidth) return <CompactRangeSetting key={id} label={label} value={Math.min(Number(saved), pageWidthMaximum)} minimum={minimum} maximum={pageWidthMaximum} step={10} suffix="px" disabled={disabled} description={description} onChange={(value) => update(id, String(value))} dark={dark} />;
      return <CompactStepper key={id} label={label} value={zoom ? `${Math.round(Number(saved) * 100)}%` : `${saved}px`} disabled={disabled} onMinus={() => update(id, String(Math.max(minimum, Number((Number(saved) - step).toFixed(2)))))} onPlus={() => update(id, String(Math.min(maximum, Number((Number(saved) + step).toFixed(2)))))} dark={dark} />;
    }
    if (!setting.options) return null;
    const options = READER_SETTINGS_CATALOG.optionGroups[setting.options].map((option) => ({ value: option.value, label: option.label['zh-CN'] }));
    return <CompactSettingOptions key={id} label={label} value={saved} options={options} disabled={disabled} description={description} disambiguateLabels={id === 'quickFontSize' || id === 'lineHeight'} onChange={(value) => update(id, value)} dark={dark} />;
  }
  function sectionView(section: typeof sections[number]) {
    const entries = READER_SETTINGS_CATALOG.settings.filter((setting) => setting.section === section.id && setting.formats.some((format) => format === readerType));
    if (!entries.length) return null;
    if (section.id === 'top' || section.id === 'reset') return <div key={section.id} className="space-y-3">{entries.map(control)}</div>;
    return <ReaderSettingsSection key={section.id} title={t(section.label['zh-CN'])} icon={section.id === 'textAppearance' || section.id === 'paragraph' ? Type : SlidersHorizontal} dark={dark} nested={section.advanced}>{entries.map(control)}</ReaderSettingsSection>;
  }
  return <div data-pwa-scroll="true" className="mt-3 min-h-0 flex-1 space-y-3 overflow-auto overscroll-contain pr-1 text-sm">
    {sections.filter((section) => !section.advanced && section.id !== 'reset').map(sectionView)}
    {panel === 'settings' ? <section className="shuku-reader-control-border overflow-hidden rounded-2xl border">
      <button type="button" className="flex min-h-14 w-full items-center gap-3 px-4" aria-expanded={advanced} aria-controls="reader-advanced-settings" onClick={() => setAdvanced(!advanced)}><SlidersHorizontal size={18} /><span className="flex-1 text-left">{t('高级设置')}</span><ChevronDown size={18} /></button>
      <div id="reader-advanced-settings" className="shuku-reader-advanced-settings" data-expanded={advanced ? 'true' : 'false'}><div className="min-h-0 overflow-hidden space-y-3 p-3">{sections.filter((section) => section.advanced).map(sectionView)}</div></div>
    </section> : null}
    {sections.filter((section) => section.id === 'reset').map(sectionView)}
  </div>;
}

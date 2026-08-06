'use client';

import type { ReaderCapabilities, ReaderKind, ReaderPreferences } from '@shuku/reader-core';
import { BookOpen, Bookmark, Check, ChevronDown, ChevronLeft, ChevronRight, Clock3, Highlighter, LayoutTemplate, ListTree, Minus, MousePointer2, NotebookPen, Palette, Plus, RotateCcw, Rows2, Rows3, Rows4, Settings, SlidersHorizontal, Sparkles, Trash2, Type, X, type LucideIcon } from 'lucide-react';
import { useEffect, useRef, useState, type CSSProperties, type MouseEvent, type ReactNode, type SyntheticEvent } from 'react';
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
  READER_FONT_WEIGHT_OPTIONS,
  READER_FONT_SIZE_OPTIONS,
  READER_LINE_HEIGHT_OPTIONS,
  READER_LETTER_SPACING_OPTIONS,
  READER_PAGE_MARGIN_OPTIONS,
  READER_PROGRESS_STYLE_OPTIONS,
  READER_COMIC_FLOW_OPTIONS,
  READER_PAGE_GAP_OPTIONS,
  READER_PDF_FLOW_OPTIONS,
  READER_PDF_ROTATION_OPTIONS,
  READER_PDF_CROP_OPTIONS,
  READER_PARAGRAPH_INDENT_OPTIONS,
  READER_PARAGRAPH_SPACING_OPTIONS,
  READER_PAGE_TURN_ANIMATION_OPTIONS,
  READER_PDF_FIT_OPTIONS,
  READER_SPREAD_MODE_OPTIONS,
  READER_THEME_OPTIONS,
  READER_TAP_ZONE_OPTIONS,
  READER_TEXT_ALIGN_OPTIONS,
  closestReaderOptionValue,
  type ReaderFontFamily
} from './reader-preference-options';
import type { ReaderBookmark } from './v3/bookmarks';
import { resolveActiveEpubNavigationIndex } from './v3/epub-navigation';
import type { ReaderInteractionPolicy } from './v3/adapters/reader-interaction';
import { hasActiveTextSelection, isReaderControlTarget, readerKeyIntent, readerPinchZoom, readerPointerIntentInViewport, readerSwipeIntent, type ReaderInputIntent } from './v3/input-router';
import {
  MOBILE_READER_VIEWPORT_MAXIMUM,
  READER_PAGE_WIDTH_MINIMUM,
  readerPageWidthSliderMaximum
} from './v3/page-width';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import { ReaderControlNavButton, ReaderSegmentedControl } from './ui/reader-control-primitives';
import { createScreenWakeLockController, readerWakeLockPort } from './screen-wake-lock';

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
  manualTheme: ReaderTheme;
  themeMode: ReaderPreferences['appearance']['themeMode'];
  progressStyle: ReaderPreferences['display']['progressStyle'];
  showClock: boolean;
  tapZones: ReaderPreferences['interaction']['tapZones'];
  swipePageTurn: boolean;
  keyboardPageTurn: boolean;
  volumeKeyPageTurn: boolean;
  keepScreenAwake: boolean;
  fontSize: number;
  lineHeight: number;
  pageWidth: number;
  fontFamily: ReaderFontFamily;
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
  allowPublisherColors: boolean;
  allowPublisherFonts: boolean;
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

function foliateLocationLabel(extra: Record<string, unknown>) {
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
  const settingsRef = useRef(settings);
  const handleInputIntentRef = useRef<(intent: ReaderInputIntent | null) => void>(() => undefined);
  const panelElementRef = useRef<HTMLDivElement | null>(null);
  const panelReturnFocusRef = useRef<HTMLElement | null>(null);
  const [controlsVisible, setControlsVisible] = useState(false);
  const [panel, setPanel] = useState<ReaderPanel | null>(null);
  const [annotationTab, setAnnotationTab] = useState<'book' | 'mine'>('book');
  const [notesTab, setNotesTab] = useState<'bookmarks' | 'annotations'>('bookmarks');
  const [advancedSettingsOpen, setAdvancedSettingsOpen] = useState(false);
  const [bookmarkNotice, setBookmarkNotice] = useState('');
  const [clockTime, setClockTime] = useState(() => new Date());
  const [readerViewportWidth, setReaderViewportWidth] = useState(1350);
  const wakeLockPort = typeof navigator === 'undefined' ? null : readerWakeLockPort(navigator);
  const wakeLockSupported = wakeLockPort !== null;
  const navItems = navigationItems ?? [];
  const orderedBookmarks = [...bookmarks].sort((left, right) => left.percent - right.percent || left.createdAt.localeCompare(right.createdAt));
  const [progressScrubPercent, setProgressScrubPercent] = useState<number | null>(null);
  const dark = isDarkReaderTheme(settings.theme);
  const themeSurface = readerThemeSurfaces[settings.theme];
  const availableNavigationItems = navItems.length > 0 ? navItems : volumeNavigation?.pages ?? [];
  const chapterNavigationItems = readerType === 'reflowable'
    ? availableNavigationItems.filter((item) => Boolean(item.href))
    : availableNavigationItems;
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
  const locationLabel = readerType === 'reflowable' ? foliateLocationLabel(progressExtra) : null;
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
    handleInputIntent(readerPointerIntentInViewport(clientX, clientY, bounds, readerDirectionRef.current, settingsRef.current.tapZones));
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
    const activeControls = controlsRef.current;
    if (item.href && capabilitiesRef.current?.canJumpToHref !== false && activeControls?.jumpToHref) {
      await activeControls.jumpToHref(item.href);
    } else if (capabilitiesRef.current?.canJumpToIndex !== false && activeControls?.jumpToIndex) {
      await activeControls.jumpToIndex(item.index);
    } else {
      const total = progress.total ?? chapterNavigationItems.length;
      const percent = total > 1 ? ((item.index - 1) / (total - 1)) * 100 : 0;
      await jumpToPercent(percent);
    }
    if (dismissPanel) closePanel();
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

              {panel === 'toc' && volumeNavigation ? (
                <VolumeNavigationPanel
                  navigation={volumeNavigation}
                  readerType={readerType}
                  activeItemKey={currentNavigationItem ? navigationItemKey(currentNavigationItem) : null}
                  dark={dark}
                  onJumpItem={(item) => {
                    void jumpToItem(item);
                  }}
                />
              ) : null}

              {panel === 'toc' && !volumeNavigation ? (
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
                        ? i18nAttribute("当前版本尚未建立注释索引；后续接入 EPUB 脚注与尾注解析后会集中显示在这里。")
                        : i18nAttribute("划线、批注与跨设备同步的数据层尚未接入；这里先保留统一入口与完整的响应式结构。")}
                    </p>
                  </div>
                </div>
              ) : null}

              {panel === 'appearance' ? (
                <div data-pwa-scroll="true" className="mt-3 min-h-0 flex-1 space-y-3 overflow-auto overscroll-contain pr-1 text-sm">
                  <ThemeSwatches
                    value={settings.theme}
                    onChange={(value) => updateSettings({ theme: value as ReaderTheme, themeMode: 'manual' })}
                    dark={dark}
                  />
                  <ReaderToggleRow
                    label={i18nAttribute("跟随系统明暗")}
                    description={i18nAttribute("浅色使用白天主题，深色使用夜间主题")}
                    checked={settings.themeMode === 'system'}
                    onChange={(checked) => updateSettings({ themeMode: checked ? 'system' : 'manual', theme: checked ? settings.theme : settings.manualTheme })}
                    dark={dark}
                  />
                  {readerType === 'reflowable' ? (
                    <ReaderSettingsSection icon={Type} title={i18nAttribute("文字外观")} dark={dark}>
                      <CompactStepper label={i18nAttribute("字号")} value={`${settings.fontSize}px`} onMinus={() => updateSettings({ fontSize: Math.max(14, settings.fontSize - 1) })} onPlus={() => updateSettings({ fontSize: Math.min(30, settings.fontSize + 1) })} dark={dark} />
                      <CompactSettingOptions label={i18nAttribute("快捷字号")} value={closestReaderOptionValue(settings.fontSize, readerFontSizeOptions)} options={readerFontSizeOptions} disambiguateLabels onChange={(value) => updateSettings({ fontSize: Number(value) })} dark={dark} />
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
                      <CompactSettingOptions label={i18nAttribute("字重")} value={String(settings.fontWeight)} options={READER_FONT_WEIGHT_OPTIONS} onChange={(value) => updateSettings({ fontWeight: Number(value) as ReaderSettings['fontWeight'] })} dark={dark} />
                      <CompactSettingOptions label={i18nAttribute("字间距")} value={String(settings.letterSpacing)} options={READER_LETTER_SPACING_OPTIONS} onChange={(value) => updateSettings({ letterSpacing: Number(value) as ReaderSettings['letterSpacing'] })} dark={dark} />
                      <CompactSettingOptions label={i18nAttribute("页边距")} value={settings.pageMargin} options={READER_PAGE_MARGIN_OPTIONS} onChange={(value) => updateSettings({ pageMargin: value as ReaderSettings['pageMargin'] })} dark={dark} />
                      <CompactRangeSetting
                        label={i18nAttribute("页宽")}
                        value={Math.min(pageWidth, pageWidthMaximum)}
                        minimum={READER_PAGE_WIDTH_MINIMUM}
                        maximum={pageWidthMaximum}
                        step={10}
                        suffix="px"
                        disabled={mobilePageWidth}
                        description={mobilePageWidth ? i18nAttribute("手机模式下自动使用可视区域宽度") : undefined}
                        onChange={(value) => updateSettings({ pageWidth: value })}
                        dark={dark}
                      />
                    </ReaderSettingsSection>
                  ) : readerType === 'comic' ? (
                    <ReaderSettingsSection icon={Palette} title={i18nAttribute("画面外观")} dark={dark}>
                      <CompactRangeSetting label={i18nAttribute("页宽")} value={Math.min(pageWidth, pageWidthMaximum)} minimum={READER_PAGE_WIDTH_MINIMUM} maximum={pageWidthMaximum} step={10} suffix="px" disabled={mobilePageWidth} description={mobilePageWidth ? i18nAttribute("手机模式下自动使用可视区域宽度") : undefined} onChange={(value) => updateSettings({ comicPageWidth: value })} dark={dark} />
                      {capabilities?.canZoom !== false ? <CompactStepper label={i18nAttribute("缩放")} value={`${Math.round(settings.comicZoom * 100)}%`} onMinus={() => updateSettings({ comicZoom: Math.max(0.6, Number((settings.comicZoom - 0.1).toFixed(1))) })} onPlus={() => updateSettings({ comicZoom: Math.min(2.4, Number((settings.comicZoom + 0.1).toFixed(1))) })} dark={dark} /> : null}
                    </ReaderSettingsSection>
                  ) : (
                    <ReaderSettingsSection icon={Palette} title={i18nAttribute("页面外观")} dark={dark}>
                      <CompactRangeSetting label={i18nAttribute("页宽")} value={Math.min(pageWidth, pageWidthMaximum)} minimum={READER_PAGE_WIDTH_MINIMUM} maximum={pageWidthMaximum} step={10} suffix="px" disabled={mobilePageWidth} description={mobilePageWidth ? i18nAttribute("手机模式下自动使用可视区域宽度") : undefined} onChange={(value) => updateSettings({ pdfPageWidth: value })} dark={dark} />
                      {capabilities?.canZoom !== false ? <CompactStepper label={i18nAttribute("缩放")} value={`${Math.round(settings.pdfZoom * 100)}%`} onMinus={() => updateSettings({ pdfZoom: Math.max(0.6, Number((settings.pdfZoom - 0.1).toFixed(1))) })} onPlus={() => updateSettings({ pdfZoom: Math.min(2.4, Number((settings.pdfZoom + 0.1).toFixed(1))) })} dark={dark} /> : null}
                    </ReaderSettingsSection>
                  )}
                </div>
              ) : null}

              {panel === 'settings' ? (
                <div data-pwa-scroll="true" className="mt-3 min-h-0 flex-1 space-y-3 overflow-auto overscroll-contain pr-1 text-sm">
                  <div className="grid items-start gap-3">
                    <ReaderSettingsSection icon={Clock3} title={i18nAttribute("阅读界面")} dark={dark}>
                      <CompactSettingOptions label={i18nAttribute("进度显示")} value={settings.progressStyle} options={READER_PROGRESS_STYLE_OPTIONS} onChange={(value) => updateSettings({ progressStyle: value as ReaderSettings['progressStyle'] })} dark={dark} />
                      <div className="grid gap-2.5">
                        <ReaderToggleRow label={i18nAttribute("常显时钟")} checked={settings.showClock} onChange={(checked) => updateSettings({ showClock: checked })} dark={dark} />
                        <ReaderToggleRow label={i18nAttribute("保持屏幕唤醒")} description={wakeLockSupported ? undefined : i18nAttribute("当前浏览器不支持保持屏幕唤醒")} checked={settings.keepScreenAwake} disabled={!wakeLockSupported} onChange={(checked) => updateSettings({ keepScreenAwake: checked })} dark={dark} />
                      </div>
                    </ReaderSettingsSection>
                    <ReaderSettingsSection icon={BookOpen} title={i18nAttribute("翻页设置")} dark={dark}>
                      {readerType === 'reflowable' ? (
                        <CompactSettingOptions label={i18nAttribute("动画")} value={settings.ebookPageTurnAnimation} options={READER_PAGE_TURN_ANIMATION_OPTIONS} onChange={(value) => updateSettings({ ebookPageTurnAnimation: value as EbookPageTurnAnimation })} dark={dark} />
                      ) : readerType === 'comic' ? (
                        <CompactSettingOptions label={i18nAttribute("动画")} value={settings.comicPageTurnAnimation} options={READER_PAGE_TURN_ANIMATION_OPTIONS} onChange={(value) => updateSettings({ comicPageTurnAnimation: value as ComicPageTurnAnimation })} dark={dark} />
                      ) : null}
                      <CompactSettingOptions label={i18nAttribute("点击区域")} value={settings.tapZones} options={READER_TAP_ZONE_OPTIONS} onChange={(value) => updateSettings({ tapZones: value as ReaderSettings['tapZones'] })} dark={dark} />
                      <ReaderToggleRow label={i18nAttribute("滑动翻页")} checked={settings.swipePageTurn} onChange={(checked) => updateSettings({ swipePageTurn: checked })} dark={dark} />
                    </ReaderSettingsSection>
                  </div>

                  <ReaderSettingsSection icon={LayoutTemplate} title={i18nAttribute("排版")} dark={dark}>
                    {readerType === 'reflowable' ? (
                      <>
                        <CompactSettingOptions label={i18nAttribute("阅读方式")} value={settings.ebookFlow} options={READER_FLOW_OPTIONS} onChange={(value) => updateSettings({ ebookFlow: value as EbookFlow })} dark={dark} />
                        <CompactSettingOptions label={i18nAttribute("页面")} value={settings.ebookSpreadMode} options={READER_SPREAD_MODE_OPTIONS} onChange={(value) => updateSettings({ ebookSpreadMode: value as EbookSpreadMode })} dark={dark} />
                      </>
                    ) : readerType === 'comic' ? (
                      <>
                        <CompactSettingOptions label={i18nAttribute("阅读方式")} value={settings.comicFlow} options={READER_COMIC_FLOW_OPTIONS} onChange={(value) => updateSettings({ comicFlow: value as ReaderSettings['comicFlow'] })} dark={dark} />
                        <CompactSettingOptions label={i18nAttribute("模式")} value={settings.comicMode} options={READER_SPREAD_MODE_OPTIONS.filter((option) => option.value !== 'auto')} disabled={settings.comicFlow === 'vertical'} onChange={(value) => updateSettings({ comicMode: value as ComicMode })} dark={dark} />
                        <CompactSettingOptions label={i18nAttribute("方向")} value={settings.comicDirection} options={READER_COMIC_DIRECTION_OPTIONS} disabled={settings.comicFlow === 'vertical'} onChange={(value) => updateSettings({ comicDirection: value as ComicDirection })} dark={dark} />
                        <CompactSettingOptions label={i18nAttribute("适配")} value={settings.imageFit} options={READER_COMIC_IMAGE_FIT_OPTIONS} onChange={(value) => updateSettings({ imageFit: value as ComicImageFit })} dark={dark} />
                        <ReaderToggleRow label={i18nAttribute("双页时封面单独显示")} checked={settings.comicCoverSingle} disabled={settings.comicFlow === 'vertical' || settings.comicMode !== 'double'} onChange={(checked) => updateSettings({ comicCoverSingle: checked })} dark={dark} />
                        <CompactSettingOptions label={i18nAttribute("页间距")} value={String(settings.comicPageGap)} options={READER_PAGE_GAP_OPTIONS} disabled={settings.comicFlow === 'vertical'} onChange={(value) => updateSettings({ comicPageGap: Number(value) as ReaderSettings['comicPageGap'] })} dark={dark} />
                      </>
                    ) : (
                      <>
                        <CompactSettingOptions label={i18nAttribute("阅读方式")} value={settings.pdfFlow} options={READER_PDF_FLOW_OPTIONS} onChange={(value) => updateSettings({ pdfFlow: value as ReaderSettings['pdfFlow'] })} dark={dark} />
                        <CompactSettingOptions label={i18nAttribute("适配")} value={settings.pdfFit} options={READER_PDF_FIT_OPTIONS} onChange={(value) => updateSettings({ pdfFit: value as PdfFit })} dark={dark} />
                        <CompactSettingOptions label={i18nAttribute("页面旋转")} value={String(settings.pdfRotation)} options={READER_PDF_ROTATION_OPTIONS} onChange={(value) => updateSettings({ pdfRotation: Number(value) as ReaderSettings['pdfRotation'] })} dark={dark} />
                        <CompactSettingOptions label={i18nAttribute("自动裁白边")} value={settings.pdfCropMargins} options={READER_PDF_CROP_OPTIONS} onChange={(value) => updateSettings({ pdfCropMargins: value as ReaderSettings['pdfCropMargins'] })} dark={dark} />
                      </>
                    )}
                  </ReaderSettingsSection>

                  {readerType === 'reflowable' ? (
                    <ReaderSettingsSection icon={Sparkles} title={i18nAttribute("智能优化")} dark={dark}>
                      <ReaderToggleRow label={i18nAttribute("安全优化")} description={i18nAttribute("避免重复缩进，并为普通正文补齐段首缩进")} checked={settings.smartOptimization} onChange={(checked) => updateSettings({ smartOptimization: checked })} dark={dark} />
                      <ReaderToggleRow label={i18nAttribute("重复缩进去重")} checked={settings.deduplicateIndent} disabled={!settings.smartOptimization} onChange={(checked) => updateSettings({ deduplicateIndent: checked })} dark={dark} />
                      <ReaderToggleRow label={i18nAttribute("无缩进正文补齐")} checked={settings.indentUnindented} disabled={!settings.smartOptimization} onChange={(checked) => updateSettings({ indentUnindented: checked })} dark={dark} />
                    </ReaderSettingsSection>
                  ) : null}

                  <section className={cn('shuku-reader-control-border overflow-hidden rounded-2xl border', dark ? 'bg-white/[0.035]' : 'bg-white/45')}>
                    <button type="button" className="flex min-h-14 w-full items-center gap-3 px-4 text-left" aria-expanded={advancedSettingsOpen} aria-controls="reader-advanced-settings" onClick={() => setAdvancedSettingsOpen((open) => !open)}>
                      <SlidersHorizontal size={18} className="shrink-0 opacity-70" />
                      <span className="min-w-0 flex-1 font-semibold"><I18nText>高级设置</I18nText></span>
                      <ChevronDown size={18} className={cn('shrink-0 transition-transform duration-300 motion-reduce:transition-none', advancedSettingsOpen ? 'rotate-180' : '')} />
                    </button>
                    <div id="reader-advanced-settings" className="shuku-reader-advanced-settings" data-expanded={advancedSettingsOpen ? 'true' : 'false'}>
                      <div className="shuku-reader-control-border min-h-0 space-y-3 border-t p-3">
                        {readerType === 'reflowable' ? (
                          <ReaderSettingsSection icon={Type} title={i18nAttribute("段落与内容样式")} dark={dark} nested>
                            <CompactSettingOptions label={i18nAttribute("段首缩进")} value={String(settings.paragraphIndent)} options={READER_PARAGRAPH_INDENT_OPTIONS} onChange={(value) => updateSettings({ paragraphIndent: Number(value) })} dark={dark} />
                            <CompactSettingOptions label={i18nAttribute("段间距")} value={String(settings.paragraphSpacing)} options={READER_PARAGRAPH_SPACING_OPTIONS} onChange={(value) => updateSettings({ paragraphSpacing: Number(value) })} dark={dark} />
                            <CompactSettingOptions label={i18nAttribute("文本对齐")} value={settings.textAlign} options={READER_TEXT_ALIGN_OPTIONS} onChange={(value) => updateSettings({ textAlign: value as ReaderSettings['textAlign'] })} dark={dark} />
                            <ReaderToggleRow label={i18nAttribute("保留出版方行高")} checked={settings.preservePublisherStyles} onChange={(checked) => updateSettings({ preservePublisherStyles: checked })} dark={dark} />
                            <ReaderToggleRow label={i18nAttribute("允许出版方颜色")} checked={settings.allowPublisherColors} onChange={(checked) => updateSettings({ allowPublisherColors: checked })} dark={dark} />
                            <ReaderToggleRow label={i18nAttribute("允许出版方字体")} checked={settings.allowPublisherFonts} onChange={(checked) => updateSettings({ allowPublisherFonts: checked })} dark={dark} />
                          </ReaderSettingsSection>
                        ) : readerType === 'comic' ? (
                          <ReaderSettingsSection icon={Palette} title={i18nAttribute("漫画画面")} dark={dark} nested>
                            <CompactSettingOptions label={i18nAttribute("画质")} value={settings.imageVariant} options={READER_COMIC_IMAGE_VARIANT_OPTIONS} onChange={(value) => updateSettings({ imageVariant: value as ComicImageVariant })} dark={dark} />
                          </ReaderSettingsSection>
                        ) : null}
                        <ReaderSettingsSection icon={MousePointer2} title={i18nAttribute("操作方式")} dark={dark} nested>
                          <ReaderToggleRow label={i18nAttribute("键盘翻页")} checked={settings.keyboardPageTurn} onChange={(checked) => updateSettings({ keyboardPageTurn: checked })} dark={dark} />
                          <ReaderToggleRow label={i18nAttribute("音量键翻页")} description={i18nAttribute("默认关闭，部分浏览器可能不会转发音量键事件")} checked={settings.volumeKeyPageTurn} onChange={(checked) => updateSettings({ volumeKeyPageTurn: checked })} dark={dark} />
                        </ReaderSettingsSection>
                      </div>
                    </div>
                  </section>

                  {onResetSettings ? (
                    <button
                      type="button"
                      onClick={() => { void onResetSettings(); keepControlsOpen(); }}
                      aria-label={i18nAttribute("恢复阅读默认设置")}
                      className={cn('shuku-reader-control-border flex min-h-10 w-full items-center justify-center gap-2 rounded-xl border px-3 text-xs font-medium transition active:scale-[0.98]', dark ? 'hover:bg-white/10' : 'hover:bg-stone-900/5')}
                    >
                      <RotateCcw size={15} />
                      <I18nText>恢复阅读默认设置</I18nText></button>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="shuku-reader-console-home shuku-reader-console-bar flex min-w-0 shrink-0" data-reader-console-controls="true">
          <div className="flex min-w-0 flex-1 flex-col md:hidden">
            <div data-reader-mobile-progress-controls="true" className="px-2 pb-1 pt-2">
              <div className="flex min-w-0 items-center gap-1">
                <button
                  type="button"
                  aria-label={i18nAttribute("上一章")}
                  data-reader-chapter-target={previousChapter?.href ?? previousChapter?.index}
                  disabled={!previousChapter}
                  onClick={() => { if (previousChapter) void navigateToItem(previousChapter, false); }}
                  className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition active:scale-[0.97] disabled:opacity-35', dark ? 'hover:bg-white/10' : 'hover:bg-stone-900/5')}
                >
                  <ChevronLeft size={20} />
                </button>
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
                className="h-7 min-w-0 flex-1 cursor-pointer disabled:cursor-not-allowed"
                style={{ accentColor }}
              />
                <button
                  type="button"
                  aria-label={i18nAttribute("下一章")}
                  data-reader-chapter-target={nextChapter?.href ?? nextChapter?.index}
                  disabled={!nextChapter}
                  onClick={() => { if (nextChapter) void navigateToItem(nextChapter, false); }}
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
            {readerType !== 'reflowable' || navItems.length > 0 || volumeNavigation ? (
              <ReaderControlNavButton layout="dock" icon={ListTree} label={i18nAttribute("目录")} selected={panel === 'toc'} expanded={panel === 'toc'} panelTrigger="toc" onClick={(event) => togglePanel('toc', event.currentTarget)} dark={dark} />
            ) : null}
            <ReaderControlNavButton layout="dock" icon={NotebookPen} label={i18nAttribute("笔记")} active={bookmarkActive} selected={panel === 'notes'} expanded={panel === 'notes'} panelTrigger="notes" onClick={(event) => { setNotesTab('bookmarks'); togglePanel('notes', event.currentTarget); }} dark={dark} />
            <div className="min-w-0 flex-1 items-center gap-2 px-2 md:flex lg:px-4">
            <button type="button" aria-label={i18nAttribute("上一章")} data-reader-chapter-target={previousChapter?.href ?? previousChapter?.index} disabled={!previousChapter} onClick={() => { if (previousChapter) void navigateToItem(previousChapter, false); }} className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition active:scale-[0.97] disabled:opacity-35', dark ? 'hover:bg-white/10' : 'hover:bg-stone-900/5')}>
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
            <button type="button" aria-label={i18nAttribute("下一章")} data-reader-chapter-target={nextChapter?.href ?? nextChapter?.index} disabled={!nextChapter} onClick={() => { if (nextChapter) void navigateToItem(nextChapter, false); }} className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition active:scale-[0.97] disabled:opacity-35', dark ? 'hover:bg-white/10' : 'hover:bg-stone-900/5')}>
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
      <ReaderSegmentedControl
        ariaLabel={i18nAttribute(label)}
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
  );
}

function CompactStepper({ label, value, onMinus, onPlus, dark }: { label: string; value: string; onMinus: () => void; onPlus: () => void; dark: boolean }) {
  const { t: i18nAttribute } = useAttributeI18n();
  return (
    <div className="flex items-center gap-3 min-[900px]:max-w-[32rem]">
      <span className="w-9 shrink-0 text-xs font-medium opacity-55">{i18nAttribute(label)}</span>
      <div className={cn('shuku-reader-control-border flex min-w-0 flex-1 items-center rounded-xl border p-1', dark ? 'bg-white/[0.07]' : 'bg-stone-900/[0.055]')}>
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
  return (
    <label className={cn('shuku-reader-control-border flex min-h-11 items-center gap-3 rounded-xl border px-3 py-2', disabled && 'opacity-45', dark ? 'bg-white/[0.045]' : 'bg-white/55')}>
      <span className="min-w-0 flex-1">
        <span className="block text-xs font-medium">{label}</span>
        {description ? <span className="mt-0.5 block text-[11px] leading-4 opacity-55">{description}</span> : null}
      </span>
      <input type="checkbox" className="peer sr-only" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
      <span data-reader-toggle-control="true" aria-hidden="true" className={cn('relative h-6 w-11 shrink-0 rounded-full border transition-colors peer-focus-visible:ring-2', checked ? 'shuku-reader-accent-toggle' : dark ? 'shuku-reader-control-border bg-white/10' : 'shuku-reader-control-border bg-stone-900/10')}>
        <span data-reader-toggle-knob="true" className={cn('absolute left-0.5 top-1/2 h-5 w-5 -translate-y-1/2 rounded-full bg-white shadow-sm transition-transform', checked && 'translate-x-5')} />
      </span>
    </label>
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
    selected ? 'shuku-reader-accent-solid' : dark ? 'hover:bg-white/10' : 'hover:bg-stone-100'
  );
}

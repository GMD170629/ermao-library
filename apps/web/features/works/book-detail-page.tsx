'use client';

import { apiV2Fetch, apiV2Request } from '@/lib/api-v2';
import type {
  AccountResponse,
  EditionResponse,
  SplitEditionResponse,
  VolumeTransferResponse,
  WorkDetailResponse,
  WorkResponse
} from '@/generated/api-v2';

import {
  BarChart3,
  BookOpen,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Circle,
  Database,
  Download,
  Edit3,
  Ellipsis,
  EyeOff,
  Headphones,
  ImageUp,
  Images,
  MoveRight,
  Play,
  Save,
  Send,
  Settings2,
  Trash2,
  X
} from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { Cover } from '../../components/book/cover';
import { MobileNavigationTrigger } from '../../components/layout/mobile-navigation';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { useToast } from '../../components/ui/feedback';
import { Select } from '../../components/ui/select';
import { VolumeSelect } from '../../components/ui/volume-select';
import { withBasePath } from '../../lib/base-path';
import { workResponseToView } from '../../lib/api-v2/adapters';
import type { MediaKind, ReadingStatus, WorkDetailTabKey, WorkView } from '../../types/work';
import { useAudioPlayback } from '../audio/audio-playback-provider';
import { resolveChapterReadingStates } from './chapter-reading-state';
import { MetadataLookupModal } from './metadata-lookup-modal';
import { KindleSendModal } from './kindle-send-modal';
import { I18nText } from '@/i18n/provider';
import type { MessageValues } from '@/i18n/messages';
import {
  audioDetailProjection,
  detailTabsForBook,
  editionsForDetailTab,
  formatDuration,
  mediaKindForEdition,
  resolveVolumeIdForSections,
  resolvedDetailTab,
  selectedEditionForDetailTab,
  workDetailTabHref
} from './work-detail-tabs';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

const DEFAULT_DESCRIPTION = '暂无简介，可在详情页补充元数据。';
const DESKTOP_CHAPTER_PAGE_SIZE = 120;
const DETAIL_TAB_STORAGE_PREFIX = 'shuku:work-detail-tab:';

const statusOptions = [
  { value: 'UNREAD', label: '未读' },
  { value: 'READING', label: '在读' },
  { value: 'FINISHED', label: '已读' }
];

const listeningStatusOptions = [
  { value: 'UNREAD', label: '未听' },
  { value: 'READING', label: '在听' },
  { value: 'FINISHED', label: '听完' }
];

const comicStatusOptions = [
  { value: 'UNREAD', label: '未看' },
  { value: 'READING', label: '在看' },
  { value: 'FINISHED', label: '看完' }
];

function storedDetailTab(workId: string): WorkDetailTabKey | null {
  try {
    const value = window.localStorage.getItem(`${DETAIL_TAB_STORAGE_PREFIX}${workId}`);
    return value === 'EBOOK' || value === 'COMIC' || value === 'AUDIOBOOK' || value === 'STRUCTURE' ? value : null;
  } catch {
    return null;
  }
}

function rememberDetailTab(workId: string, tab: WorkDetailTabKey) {
  try {
    window.localStorage.setItem(`${DETAIL_TAB_STORAGE_PREFIX}${workId}`, tab);
  } catch {
    // The authenticated server preference remains authoritative when storage is unavailable.
  }
}

type ReadingUnitView = {
  id: string;
  unitType: string;
  title: string;
  href?: string;
  mediaType?: string | null;
  sortOrder: number;
  size?: string | number | null;
  durationMs?: number | null;
  startMs?: number | null;
  endMs?: number | null;
  fileId?: string | null;
  current?: boolean;
};

type VolumeSectionView = {
  id: string;
  editionId?: string | null;
  title: string;
  index?: number | null;
  fileId?: string | null;
  pageCount?: number | null;
  coverUrl: string;
  progress?: number;
  lastReadAt?: string | null;
  currentHref?: string | null;
  currentSectionIndex?: number | null;
  currentChapterTitle?: string | null;
  currentChapterSortOrder?: number | null;
  durationMs?: number | null;
};

type ActiveWorkMedia = {
  key: MediaKind;
  formatLabel: string;
  selectedEditionId: string | null;
  selectedEditionName: string | null;
  status: ReadingStatus;
  progress: number;
  positionLabel: string;
  durationMs?: number | null;
  narrator?: string | null;
  currentUnitId?: string | null;
  primaryAction: { label: string; href: string } | null;
  units: ReadingUnitView[];
  volumes: VolumeSectionView[];
  tracks?: WorkView['files'];
};

type PageMeta = { page: number; pageSize: number; total: number; totalPages: number };
type WorksResponse = { items: WorkResponse[]; total: number; page: number; pageSize: number };
type StructureVolume = Pick<WorkView['volumes'][number], 'id' | 'editionId' | 'title'>;

const emptyReadingUnitsPage: PageMeta = {
  page: 1,
  pageSize: DESKTOP_CHAPTER_PAGE_SIZE,
  total: 0,
  totalPages: 1
};

function readableEditionId(book: WorkView | null, preferredEditionId?: string | null) {
  if (!book) return null;
  const candidates = [preferredEditionId, book.recentEditionId, book.editionId, book.primaryEditionId];
  return candidates.find((candidate) => candidate && book.editions.some((edition) => edition.id === candidate && !edition.hidden && edition.readable))
    ?? book.editions.find((edition) => !edition.hidden && edition.readable)?.id
    ?? null;
}

function readerUrlForBook(
  book: WorkView,
  volumeSections: VolumeSectionView[],
  preferredEditionId?: string | null,
  preferredVolumeId?: string | null
) {
  const editionId = readableEditionId(book, preferredEditionId);
  if (!editionId) return null;
  const volumeId = resolveVolumeIdForSections(volumeSections, preferredVolumeId, book.recentVolumeId);
  return volumeId ? `/reader/${editionId}?volume=${encodeURIComponent(volumeId)}` : `/reader/${editionId}`;
}

function readerUrlForChapter(book: WorkView, editionId: string | null, volumeId: string | null | undefined, href: string | null | undefined) {
  editionId = readableEditionId(book, editionId);
  if (!editionId) return null;
  const params = new URLSearchParams();
  if (volumeId) params.set('volume', volumeId);
  if (href) params.set('href', href);
  const query = params.toString();
  return `/reader/${editionId}${query ? `?${query}` : ''}`;
}

function readerUrlForEdition(edition: WorkView['editions'][number]) {
  if (!edition.readable) return null;
  if (mediaKindForEdition(edition) === 'AUDIOBOOK') {
    return `/works/${encodeURIComponent(edition.workId)}?detailTab=AUDIOBOOK&editionId=${encodeURIComponent(edition.id)}`;
  }
  const volumeId = edition.volumes[0]?.id;
  return `/reader/${edition.id}${volumeId ? `?volume=${encodeURIComponent(volumeId)}` : ''}`;
}

function fileName(path: string | null | undefined) {
  if (!path) return '未记录文件名';
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path;
}

function currentPositionLabel(book: WorkView) {
  const volume = book.volumes.find((item) => item.id === book.recentVolumeId);
  const parts = [
    volume && book.volumes.length > 1 ? volume.title : '',
    book.currentChapterTitle ?? ''
  ].filter(Boolean);
  if (parts.length > 0) return parts.join(' · ');
  if (book.chapter && book.chapter !== '未开始') return book.chapter;
  return '尚未开始';
}

function editionUnitLabel(edition: WorkView['editions'][number], translate: (source: string, values?: MessageValues) => string) {
  if (!edition.readable) return '原始文件';
  if (mediaKindForEdition(edition) === 'AUDIOBOOK') {
    const duration = formatDuration(edition.durationMs);
    return [
      edition.trackCount
        ? edition.trackCount === 1
          ? translate('1 个音轨')
          : translate('{value0} 个音轨', { value0: edition.trackCount })
        : translate('{value0} 章', { value0: edition.chapterCount ?? 0 }),
      duration
    ].filter(Boolean).join(' · ');
  }
  if (edition.formatValue === 'COMIC') return translate('{value0} 个卷册', { value0: edition.volumes.length });
  if (edition.formatValue === 'PDF') return translate('{value0} 页', { value0: edition.pageCount ?? 0 });
  return translate('{value0} 章', { value0: edition.chapterCount ?? 0 });
}

function formatTone(format: WorkView['formatValue']) {
  if (format === 'AUDIO') return 'border-sky-100 bg-sky-50 text-sky-700';
  if (format === 'EPUB') return 'border-emerald-100 bg-emerald-50 text-emerald-700';
  if (format === 'PDF') return 'border-rose-100 bg-rose-50 text-rose-700';
  return 'border-amber-100 bg-amber-50 text-amber-700';
}

function consumptionCopy(kind: MediaKind | null) {
  if (kind === 'AUDIOBOOK') return { progress: '收听进度', position: '当前收听', start: '开始听', resume: '继续听', status: '收听状态' };
  if (kind === 'COMIC') return { progress: '阅读进度', position: '当前卷册', start: '开始看', resume: '继续看', status: '阅读状态' };
  return { progress: '阅读进度', position: '当前位置', start: '开始阅读', resume: '继续阅读', status: '阅读状态' };
}

function legacyActiveMedia(
  book: WorkView,
  tab: WorkDetailTabKey,
  selectedEditionId: string | null,
  units: ReadingUnitView[],
  volumes: VolumeSectionView[]
): ActiveWorkMedia | null {
  if (tab === 'STRUCTURE') return null;
  const edition = selectedEditionForDetailTab(book, tab, selectedEditionId);
  if (!edition) return null;
  const group = book.mediaGroups?.find((candidate) => candidate.kind === tab);
  const progress = group?.progress ?? edition.progress ?? book.progress;
  const status = progress >= 100 ? 'FINISHED' : group?.status ?? book.statusValue;
  const copy = consumptionCopy(tab);
  const href = tab === 'AUDIOBOOK'
    ? `/works/${encodeURIComponent(book.id)}?detailTab=AUDIOBOOK&editionId=${encodeURIComponent(edition.id)}`
    : readerUrlForBook(book, volumes, edition.id, group?.recentVolumeId);
  return {
    key: tab,
    formatLabel: edition.format,
    selectedEditionId: edition.id,
    selectedEditionName: edition.versionName,
    status,
    progress,
    positionLabel: group?.positionLabel || currentPositionLabel(book),
    durationMs: group?.durationMs ?? edition.durationMs,
    narrator: edition.narrator,
    primaryAction: href ? { label: progress > 0 ? copy.resume : copy.start, href } : null,
    units,
    volumes
  };
}

function inputClassName() {
  return 'mt-2 h-11 w-full rounded-xl border border-stone-200 bg-white px-4 text-stone-900 outline-none transition focus:border-orange-300 focus:ring-4 focus:ring-orange-100/70';
}

export function BookDetailPage({ bookId }: { bookId: string }) {
  const { t: i18nAttribute } = useAttributeI18n();
  const router = useRouter();
  const searchParams = useSearchParams();
  const toast = useToast();
  const audioPlayback = useAudioPlayback();
  const requestedDetailTabValue = searchParams.get('detailTab');
  const requestedDetailTab: WorkDetailTabKey | null = requestedDetailTabValue === 'EBOOK'
    || requestedDetailTabValue === 'COMIC'
    || requestedDetailTabValue === 'AUDIOBOOK'
    || requestedDetailTabValue === 'STRUCTURE'
    ? requestedDetailTabValue
    : null;
  const requestedEditionId = searchParams.get('editionId')?.trim() || null;
  const actionsRef = useRef<HTMLDivElement>(null);
  const coverInputRef = useRef<HTMLInputElement>(null);
  const detailRequestRef = useRef<AbortController | null>(null);
  const preferenceRequestRef = useRef<AbortController | null>(null);
  const localDetailQueryRef = useRef<string | null>(null);
  const seriesScrollerRef = useRef<HTMLDivElement>(null);
  const seriesDragRef = useRef<{ pointerId: number; startX: number; scrollLeft: number; moved: boolean } | null>(null);
  const suppressSeriesClickRef = useRef(false);

  const [book, setBook] = useState<WorkView | null>(null);
  const [canManageSystem, setCanManageSystem] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [readingUnits, setReadingUnits] = useState<ReadingUnitView[]>([]);
  const [readingUnitsPage, setReadingUnitsPage] = useState<PageMeta>(emptyReadingUnitsPage);
  const [volumeSections, setVolumeSections] = useState<VolumeSectionView[]>([]);
  const [activeMedia, setActiveMedia] = useState<ActiveWorkMedia | null>(null);
  const [selectedEditionId, setSelectedEditionId] = useState<string | null>(null);
  const [selectedVolumeId, setSelectedVolumeId] = useState<string | null>(null);
  const [chapterPage, setChapterPage] = useState(1);
  const [chapterLoading, setChapterLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<WorkDetailTabKey | null>(null);
  const [contextBookId, setContextBookId] = useState(bookId);
  const [manageStructure, setManageStructure] = useState(false);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editingScope, setEditingScope] = useState<'work' | 'edition'>('work');
  const [editingEditionId, setEditingEditionId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [busyAction, setBusyAction] = useState('');
  const [metadataLookupOpen, setMetadataLookupOpen] = useState(false);
  const [kindleSendOpen, setKindleSendOpen] = useState(false);
  const [dangerActionOpen, setDangerActionOpen] = useState(false);
  const [deleteSource, setDeleteSource] = useState(false);
  const [moveTargetOpen, setMoveTargetOpen] = useState(false);
  const [movingVolume, setMovingVolume] = useState<StructureVolume | null>(null);
  const [targetSearch, setTargetSearch] = useState('');
  const [targetBooks, setTargetBooks] = useState<WorkView[]>([]);
  const [targetBooksLoading, setTargetBooksLoading] = useState(false);
  const [targetBookId, setTargetBookId] = useState('');
  const [targetEditionId, setTargetEditionId] = useState('');
  const [seriesBooks, setSeriesBooks] = useState<WorkView[]>([]);
  const [seriesTotal, setSeriesTotal] = useState(0);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [seriesCanScrollLeft, setSeriesCanScrollLeft] = useState(false);
  const [seriesCanScrollRight, setSeriesCanScrollRight] = useState(false);
  const [coverBust, setCoverBust] = useState(0);
  const [editionForm, setEditionForm] = useState({ versionName: '', publisher: '', publishedAt: '', language: '', isbn: '', identifier: '', narrator: '', description: '' });
  const [splitTarget, setSplitTarget] = useState<WorkView['editions'][number] | null>(null);
  const [splitForm, setSplitForm] = useState({ title: '', author: '', copyShelves: true });
  const [form, setForm] = useState({
    title: '',
    author: '',
    description: '',
    seriesName: '',
    seriesIndex: '',
    publishedYear: '',
    tags: '',
    status: 'UNREAD'
  });

  useEffect(() => {
    document.documentElement.dataset.shukuWorkDetail = 'true';
    return () => {
      delete document.documentElement.dataset.shukuWorkDetail;
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    apiV2Fetch('/api/v2/account', { cache: 'no-store', credentials: 'same-origin', signal: controller.signal })
      .then((response) => response.json() as Promise<AccountResponse>)
      .then((account) => setCanManageSystem(account.scopes.includes('operations:write')))
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  const loadBook = useCallback(() => {
    detailRequestRef.current?.abort();
    const controller = new AbortController();
    detailRequestRef.current = controller;
    const params = new URLSearchParams({
      chapterPage: String(chapterPage),
      chapterPageSize: String(DESKTOP_CHAPTER_PAGE_SIZE),
      unitPage: String(chapterPage),
      unitPageSize: String(DESKTOP_CHAPTER_PAGE_SIZE)
    });
    if (activeTab) params.set('detailTab', activeTab);
    if (selectedEditionId) params.set('editionId', selectedEditionId);
    if (selectedVolumeId) params.set('volumeId', selectedVolumeId);
    setChapterLoading(true);
    setError('');
    return apiV2Request<WorkDetailResponse>(
      `/api/v2/catalog/works/${bookId}?${params.toString()}`,
      { signal: controller.signal }
    )
      .then((payload) => {
        const nextBook = workResponseToView(payload);
        const rememberedTab = storedDetailTab(bookId);
        const nextTab = resolvedDetailTab(nextBook, activeTab ?? rememberedTab);
        const responseMedia = null;
        const nextReadingUnits: ReadingUnitView[] = [];
        const nextVolumeSections: VolumeSectionView[] = nextBook.volumes.map((volume) => ({
          id: volume.id,
          editionId: volume.editionId,
          title: volume.title,
          index: volume.sortOrder,
          pageCount: volume.pageCount,
          coverUrl: '',
          durationMs: volume.durationMs ?? null
        }));
        const nextActiveMedia = responseMedia ?? legacyActiveMedia(nextBook, nextTab, selectedEditionId, nextReadingUnits, nextVolumeSections);
        setBook(nextBook);
        setActiveTab(nextTab);
        setActiveMedia(nextActiveMedia);
        setReadingUnits(nextReadingUnits);
        setReadingUnitsPage(emptyReadingUnitsPage);
        setVolumeSections(nextVolumeSections);
        if (nextActiveMedia?.selectedEditionId && nextActiveMedia.selectedEditionId !== selectedEditionId) {
          setSelectedEditionId(nextActiveMedia.selectedEditionId);
        }
        const group = nextTab === 'STRUCTURE' ? null : nextBook.mediaGroups?.find((candidate) => candidate.kind === nextTab);
        setSelectedVolumeId((currentVolumeId) => (
          resolveVolumeIdForSections(
            nextVolumeSections,
            currentVolumeId,
            group?.recentVolumeId,
            nextBook.recentVolumeId
          )
        ));
        setForm({
          title: nextBook.title,
          author: nextBook.author === '未知作者' ? '' : nextBook.author,
          description: nextBook.desc === DEFAULT_DESCRIPTION ? '' : nextBook.desc,
          seriesName: nextBook.seriesName ?? '',
          seriesIndex: nextBook.seriesIndex === null ? '' : String(nextBook.seriesIndex),
          publishedYear: nextBook.publishedYear === null ? '' : String(nextBook.publishedYear),
          tags: nextBook.tags.join(', '),
          status: nextActiveMedia?.status ?? (nextBook.progress >= 100 ? 'FINISHED' : nextBook.statusValue)
        });
      })
      .catch((reason) => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return;
        setError(reason instanceof Error ? reason.message : '读取读物失败');
      })
      .finally(() => {
        if (detailRequestRef.current === controller) setChapterLoading(false);
      });
  }, [activeTab, bookId, chapterPage, selectedEditionId, selectedVolumeId]);

  useEffect(() => {
    const detailQueryKey = `${bookId}:${requestedDetailTab ?? ''}:${requestedEditionId ?? ''}`;
    if (localDetailQueryRef.current === detailQueryKey) {
      localDetailQueryRef.current = null;
      return;
    }
    detailRequestRef.current?.abort();
    // Let the latest preference write for the previous work finish via
    // keepalive, but do not let the new work's tab changes abort it.
    preferenceRequestRef.current = null;
    setContextBookId(bookId);
    setBook(null);
    setActiveMedia(null);
    setReadingUnits([]);
    setReadingUnitsPage(emptyReadingUnitsPage);
    setVolumeSections([]);
    setChapterLoading(true);
    setSelectedEditionId(requestedEditionId);
    setSelectedVolumeId(null);
    setChapterPage(1);
    setActiveTab(requestedDetailTab);
    setManageStructure(false);
  }, [bookId, requestedDetailTab, requestedEditionId]);

  useEffect(() => {
    if (contextBookId !== bookId) return;
    void loadBook();
  }, [bookId, contextBookId, loadBook]);

  useEffect(() => () => {
    detailRequestRef.current?.abort();
  }, []);

  useEffect(() => {
    function closeActions(event: MouseEvent) {
      if (!actionsRef.current?.contains(event.target as Node)) setActionsOpen(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') setActionsOpen(false);
    }
    document.addEventListener('mousedown', closeActions);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('mousedown', closeActions);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, []);

  useEffect(() => {
    if (!book?.seriesName) {
      setSeriesBooks([]);
      setSeriesTotal(0);
      return;
    }
    let active = true;
    const params = new URLSearchParams({
      visibility: 'active',
      page: '1',
      pageSize: '60',
      seriesName: book.seriesName,
      sort: 'series_index'
    });
    setSeriesLoading(true);
    apiV2Request<WorksResponse>(`/api/v2/catalog/works?${params.toString()}`)
      .then((payload) => {
        if (!active) return;
        setSeriesBooks(payload.items.map(workResponseToView));
        setSeriesTotal(payload.total);
      })
      .catch(() => {
        if (!active) return;
        setSeriesBooks([]);
        setSeriesTotal(0);
      })
      .finally(() => active && setSeriesLoading(false));
    return () => {
      active = false;
    };
  }, [book?.seriesName]);

  const updateSeriesScrollState = useCallback(() => {
    const scroller = seriesScrollerRef.current;
    if (!scroller) {
      setSeriesCanScrollLeft(false);
      setSeriesCanScrollRight(false);
      return;
    }
    setSeriesCanScrollLeft(scroller.scrollLeft > 1);
    setSeriesCanScrollRight(scroller.scrollLeft + scroller.clientWidth < scroller.scrollWidth - 1);
  }, []);

  useEffect(() => {
    const scroller = seriesScrollerRef.current;
    if (!scroller || seriesBooks.length === 0) return;
    const frame = window.requestAnimationFrame(() => {
      scroller.querySelector<HTMLElement>('[data-series-current="true"]')?.scrollIntoView({ block: 'nearest', inline: 'center' });
      updateSeriesScrollState();
    });
    const observer = new ResizeObserver(updateSeriesScrollState);
    observer.observe(scroller);
    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [bookId, seriesBooks, updateSeriesScrollState]);

  function scrollSeries(direction: -1 | 1) {
    const scroller = seriesScrollerRef.current;
    if (!scroller) return;
    scroller.scrollBy({ left: direction * Math.max(240, scroller.clientWidth * 0.75), behavior: 'smooth' });
  }

  function startSeriesDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.pointerType === 'touch' || event.button !== 0) return;
    const scroller = seriesScrollerRef.current;
    if (!scroller) return;
    seriesDragRef.current = { pointerId: event.pointerId, startX: event.clientX, scrollLeft: scroller.scrollLeft, moved: false };
  }

  function moveSeriesDrag(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = seriesDragRef.current;
    const scroller = seriesScrollerRef.current;
    if (!drag || !scroller || drag.pointerId !== event.pointerId) return;
    const distance = event.clientX - drag.startX;
    if (Math.abs(distance) > 4 && !drag.moved) {
      drag.moved = true;
      scroller.setPointerCapture(event.pointerId);
    }
    if (drag.moved) {
      event.preventDefault();
      scroller.scrollLeft = drag.scrollLeft - distance;
    }
  }

  function finishSeriesDrag(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = seriesDragRef.current;
    const scroller = seriesScrollerRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    suppressSeriesClickRef.current = drag.moved;
    seriesDragRef.current = null;
    if (scroller?.hasPointerCapture(event.pointerId)) scroller.releasePointerCapture(event.pointerId);
    window.setTimeout(() => { suppressSeriesClickRef.current = false; }, 0);
    updateSeriesScrollState();
  }

  useEffect(() => {
    if (!moveTargetOpen) return;
    let active = true;
    const timer = window.setTimeout(() => {
      setTargetBooksLoading(true);
      const params = new URLSearchParams({ visibility: 'active', pageSize: '12', page: '1' });
      if (targetSearch.trim()) params.set('search', targetSearch.trim());
      apiV2Request<WorksResponse>(`/api/v2/catalog/works?${params.toString()}`)
        .then((payload) => {
          if (!active) return;
          setTargetBooks(payload.items.map(workResponseToView).filter((item) => item.id !== bookId));
        })
        .catch((reason) => {
          if (!active) return;
          setTargetBooks([]);
          toast.error('搜索目标读物失败', reason instanceof Error ? reason.message : '请稍后重试');
        })
        .finally(() => active && setTargetBooksLoading(false));
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [bookId, moveTargetOpen, targetSearch, toast]);

  const displayBook = useMemo(() => {
    if (!book) return book;
    const edition = activeTab ? selectedEditionForDetailTab(book, activeTab, activeMedia?.selectedEditionId ?? selectedEditionId) : null;
    const coverUrl = book.coverUrl;
    return {
      ...book,
      format: activeMedia?.formatLabel || edition?.format || book.format,
      coverUrl: coverBust > 0 ? `${coverUrl}${coverUrl.includes('?') ? '&' : '?'}v=${coverBust}` : coverUrl
    };
  }, [activeMedia?.formatLabel, activeMedia?.selectedEditionId, activeTab, book, coverBust, selectedEditionId]);

  async function saveMetadata() {
    setSaving(true);
    setBusyAction('saveMetadata');
    setError('');
    setMessage('');
    try {
      await apiV2Request<WorkResponse>(`/api/v2/catalog/works/${bookId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: form.title,
          author: form.author || null,
          summary: form.description,
          metadata: {
            seriesName: form.seriesName || null,
            seriesIndex: form.seriesIndex ? Number(form.seriesIndex) : null,
            publishedYear: form.publishedYear ? Number(form.publishedYear) : null,
            tags: form.tags.split(/[,，\n]/).map((tag) => tag.trim()).filter(Boolean)
          }
        })
      });
      await loadBook();
      setEditing(false);
      setMessage('图书信息已保存');
      toast.success('图书信息已保存');
    } catch (reason) {
      const nextError = reason instanceof Error ? reason.message : '保存失败';
      setError(nextError);
      toast.error('保存失败', nextError);
    } finally {
      setSaving(false);
      setBusyAction('');
    }
  }

  function editEdition(edition: WorkView['editions'][number]) {
    setEditing(true);
    setEditingScope('edition');
    setEditingEditionId(edition.id);
    setEditionForm({
      versionName: edition.versionName ?? '', publisher: edition.publisher ?? '', publishedAt: edition.publishedAt?.slice(0, 10) ?? '',
      language: edition.language ?? '', isbn: edition.isbn ?? '', identifier: edition.identifier ?? '', narrator: edition.narrator ?? '', description: edition.description ?? ''
    });
    window.requestAnimationFrame(() => document.getElementById('work-metadata-editor')?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
  }

  async function saveEditionMetadata() {
    if (!editingEditionId) return;
    setSaving(true);
    setBusyAction('saveEditionMetadata');
    try {
      await apiV2Request<EditionResponse>(
        `/api/v2/catalog/works/${bookId}/editions/${editingEditionId}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(editionForm)
        }
      );
      await loadBook();
      setEditing(false);
      toast.success('版本信息已保存');
    } catch (reason) {
      toast.error('保存失败', reason instanceof Error ? reason.message : '保存版本信息失败');
    } finally { setSaving(false); setBusyAction(''); }
  }

  async function splitSelectedEdition() {
    if (!splitTarget || !splitForm.title.trim()) return;
    setSaving(true);
    setBusyAction(`split:${splitTarget.id}`);
    try {
      await apiV2Request<SplitEditionResponse>(
        `/api/v2/catalog/works/${bookId}/editions/${splitTarget.id}/split`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(splitForm)
        }
      );
      setSplitTarget(null);
      toast.success('版本已拆分为独立作品');
      void loadBook();
    } catch (reason) {
      toast.error('拆分失败', reason instanceof Error ? reason.message : '拆分版本失败');
    } finally { setSaving(false); setBusyAction(''); }
  }

  async function updateReadingStatus(status: string) {
    setBusyAction('status');
    setError('');
    try {
      await apiV2Request<WorkResponse>(`/api/v2/catalog/works/${bookId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          metadata: {
            readingStatus: status,
            readingMediaKind: activeMedia?.key,
            readingEditionId: activeMedia?.selectedEditionId ?? selectedEditionId,
            readingVolumeId: selectedVolumeId
          }
        })
      });
      await loadBook();
      setActiveMedia((current) => current ? { ...current, status: status as ReadingStatus } : current);
      setForm((current) => ({ ...current, status }));
      toast.success(activeMedia?.key === 'AUDIOBOOK' ? '收听状态已更新' : '阅读状态已更新');
    } catch (reason) {
      const nextError = reason instanceof Error ? reason.message : '阅读状态更新失败';
      setError(nextError);
      toast.error('阅读状态更新失败', nextError);
    } finally {
      setBusyAction('');
    }
  }

  async function postAction(path: string, successMessage: string, options: { refreshCover?: boolean; refreshBook?: boolean; busyKey?: string } = {}) {
    setSaving(true);
    setBusyAction(options.busyKey ?? path);
    setError('');
    setMessage('');
    try {
      await apiV2Request<void>(path, { method: 'POST' });
      if (options.refreshBook) await loadBook();
      if (options.refreshCover) setCoverBust(Date.now());
      setMessage(successMessage);
      toast.success(successMessage);
    } catch (reason) {
      const nextError = reason instanceof Error ? reason.message : '操作失败';
      setError(nextError);
      toast.error('操作失败', nextError);
    } finally {
      setSaving(false);
      setBusyAction('');
    }
  }

  async function convertEdition(edition: WorkView['editions'][number]) {
    const busyKey = `convert:${edition.id}`;
    setSaving(true);
    setBusyAction(busyKey);
    setError('');
    try {
      const response = await apiV2Fetch(`/api/v2/catalog/works/${bookId}/editions/${edition.id}/convert`, { method: 'POST' });
      const payload = (await response.json()) as { ok: boolean; data?: { task?: { id: string } }; error?: { message: string } };
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '加入转换队列失败');
      toast.success('已加入转换队列', '转换完成后会生成可阅读的 EPUB 版本。');
      await loadBook();
    } catch (reason) {
      const nextError = reason instanceof Error ? reason.message : '加入转换队列失败';
      setError(nextError);
      toast.error('转换失败', nextError);
    } finally {
      setSaving(false);
      setBusyAction('');
    }
  }

  async function moveVolume(volumeId: string, direction: 'up' | 'down') {
    setSaving(true);
    setBusyAction(`move:${volumeId}:${direction}`);
    setError('');
    try {
      await apiV2Request<void>(`/api/v2/catalog/works/${bookId}/volumes/${volumeId}/move`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ direction })
      });
      await loadBook();
      toast.success('卷册顺序已更新');
    } catch (reason) {
      const nextError = reason instanceof Error ? reason.message : '卷册顺序更新失败';
      setError(nextError);
      toast.error('卷册顺序更新失败', nextError);
    } finally {
      setSaving(false);
      setBusyAction('');
    }
  }

  function openMoveTarget(volume: StructureVolume) {
    setMovingVolume(volume);
    setMoveTargetOpen(true);
    setTargetSearch('');
    setTargetBooks([]);
    setTargetBookId('');
    setTargetEditionId('');
  }

  async function moveVolumeToTarget() {
    if (!movingVolume || !targetEditionId) return;
    setSaving(true);
    setBusyAction(`move-to:${movingVolume.id}`);
    setError('');
    try {
      const payload = await apiV2Request<VolumeTransferResponse>(
        `/api/v2/catalog/works/${bookId}/volumes/${movingVolume.id}/move-to`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ targetEditionId })
        }
      );
      setMoveTargetOpen(false);
      setMovingVolume(null);
      await loadBook();
      const successMessage = payload.transferMode === 'MERGED_VOLUME'
        ? '卷册已合并到目标主版本'
        : payload.transferMode === 'ADDED_MEDIA'
          ? '源版本已作为新媒介转入目标图书'
          : '源版本已作为后备版本转入目标图书';
      toast.success(successMessage);
    } catch (reason) {
      const nextError = reason instanceof Error ? reason.message : '内容转移失败';
      setError(nextError);
      toast.error('内容转移失败', nextError);
    } finally {
      setSaving(false);
      setBusyAction('');
    }
  }

  async function setIgnored(ignored: boolean) {
    setSaving(true);
    setBusyAction('ignored');
    setError('');
    try {
      await apiV2Request<WorkResponse>(`/api/v2/catalog/works/${bookId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: ignored ? 'archived' : 'active' })
      });
      await loadBook();
      toast.success(ignored ? '图书已隐藏' : '图书已恢复显示');
    } catch (reason) {
      const nextError = reason instanceof Error ? reason.message : '操作失败';
      setError(nextError);
      toast.error('操作失败', nextError);
    } finally {
      setSaving(false);
      setBusyAction('');
    }
  }

  async function deleteRecord() {
    setDangerActionOpen(false);
    setSaving(true);
    setBusyAction('delete');
    setError('');
    try {
      await apiV2Request<void>(`/api/v2/catalog/works/${bookId}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' }
      });
      toast.success(
        '已删除图书记录',
        '源文件已保留'
      );
      window.setTimeout(() => router.push('/library'), 500);
    } catch (reason) {
      const nextError = reason instanceof Error ? reason.message : '删除失败';
      setError(nextError);
      toast.error('删除失败', nextError);
      setSaving(false);
      setBusyAction('');
    }
  }

  function downloadPrimaryEdition() {
    const editionId = activeMedia?.selectedEditionId ?? selectedEditionId ?? book?.editionId ?? book?.primaryEditionId ?? null;
    if (editionId) window.location.href = withBasePath(`/api/v2/reading/editions/${editionId}/resource`);
  }

  async function uploadCover(file: File | null) {
    if (!file) return;
    setSaving(true);
    setBusyAction('uploadCover');
    setError('');
    try {
      const formData = new FormData();
      formData.append('cover', file);
      await apiV2Request<WorkResponse>(
        `/api/v2/catalog/works/${bookId}/cover/upload`,
        { method: 'POST', body: formData }
      );
      setCoverBust(Date.now());
      await loadBook();
      toast.success('自定义封面已保存');
    } catch (reason) {
      const nextError = reason instanceof Error ? reason.message : '上传封面失败';
      setError(nextError);
      toast.error('上传封面失败', nextError);
    } finally {
      setSaving(false);
      setBusyAction('');
    }
  }

  if (error && !book) {
    return <div className="rounded-2xl border border-red-100 bg-red-50 p-8 text-sm text-red-700">{error}</div>;
  }
  if (!book || !displayBook) {
    return <div className="shuku-loading-panel p-8 text-sm" role="status" aria-live="polite"><I18nText>正在读取图书详情...</I18nText></div>;
  }

  const detailTabs = detailTabsForBook(book);
  const currentTab = resolvedDetailTab(book, activeTab);
  const mediaKind = currentTab === 'STRUCTURE' ? null : currentTab;
  const mediaEditions = editionsForDetailTab(book, currentTab);
  const selectedEdition = selectedEditionForDetailTab(book, currentTab, activeMedia?.selectedEditionId ?? selectedEditionId);
  const readerEditionId = readableEditionId(book, selectedEdition?.id);
  const hasVolumeSections = volumeSections.length > 0;
  const hasChapterNavigation = currentTab === 'EBOOK' && selectedEdition?.formatValue === 'EPUB';
  const hasAudioNavigation = currentTab === 'AUDIOBOOK';
  const activeGroup = mediaKind ? book.mediaGroups?.find((candidate) => candidate.kind === mediaKind) : null;
  const activeVolumeId = resolveVolumeIdForSections(
    volumeSections,
    selectedVolumeId,
    activeGroup?.recentVolumeId,
    book.recentVolumeId
  );
  const activeVolume = volumeSections.find((volume) => volume.id === activeVolumeId) ?? null;
  const fallbackReaderUrl = currentTab === 'AUDIOBOOK' && readerEditionId
    ? `/works/${encodeURIComponent(book.id)}?detailTab=AUDIOBOOK&editionId=${encodeURIComponent(readerEditionId)}`
    : readerUrlForBook(book, volumeSections, readerEditionId, activeGroup?.recentVolumeId);
  const readerUrl = currentTab === 'AUDIOBOOK' && readerEditionId
    ? fallbackReaderUrl
    : activeMedia?.primaryAction?.href ?? fallbackReaderUrl;
  const audioProjection = audioDetailProjection(currentTab, book.id, readerEditionId, audioPlayback);
  const currentPosition = audioProjection?.positionLabel ?? (activeMedia?.positionLabel || currentPositionLabel(book));
  const currentProgress = audioProjection?.progress ?? activeMedia?.progress ?? activeGroup?.progress ?? selectedEdition?.progress ?? book.progress;
  const copy = consumptionCopy(mediaKind);
  const currentStatusOptions = currentTab === 'AUDIOBOOK' ? listeningStatusOptions : currentTab === 'COMIC' ? comicStatusOptions : statusOptions;
  const selectedTargetBook = targetBooks.find((item) => item.id === targetBookId) ?? null;
  const targetEditionOptions = selectedTargetBook?.editions ?? [];
  const movingEdition = movingVolume ? book.editions.find((edition) => edition.id === movingVolume.editionId) : null;
  const selectedTargetEdition = targetEditionOptions.find((edition) => edition.id === targetEditionId) ?? null;
  const matchingTargetEdition = movingEdition
    ? targetEditionOptions
        .filter((edition) => edition.formatValue === movingEdition.formatValue)
        .sort((left, right) => Number(right.primary) - Number(left.primary))[0] ?? null
    : null;
  const targetHasSourceMedia = movingEdition
    ? targetEditionOptions.some((edition) => mediaKindForEdition(edition) === mediaKindForEdition(movingEdition))
    : false;
  const transferPreview = matchingTargetEdition && movingEdition && matchingTargetEdition.volumes.length > 0 && movingEdition.volumes.length > 0
    ? `当前卷册将合并到同格式主版本「${matchingTargetEdition.versionName}」`
    : !targetHasSourceMedia
      ? '源版本将整体转入，并作为一种新的媒介保留'
      : '源版本将整体转入，并作为后备版本保留';
  const selectedIsGlobalRecent = selectedEdition?.id === book.recentEditionId;
  const chapterCurrentHref = activeVolume?.currentHref ?? (selectedIsGlobalRecent && (!activeVolumeId || activeVolumeId === book.recentVolumeId) ? book.currentHref : null);
  const chapterCurrentSortOrder = activeVolume?.currentChapterSortOrder ?? (selectedIsGlobalRecent && (!activeVolumeId || activeVolumeId === book.recentVolumeId) ? book.currentChapterSortOrder : null);
  const chapterProgress = activeVolume?.progress ?? (activeVolumeId === activeGroup?.recentVolumeId || !activeVolumeId ? currentProgress : 0);
  const chapterStates = resolveChapterReadingStates(readingUnits, chapterCurrentHref, chapterCurrentSortOrder, chapterProgress);
  const effectiveReadingStatus = currentProgress >= 100 ? 'FINISHED' : activeMedia?.status ?? activeGroup?.status ?? book.statusValue;
  const primaryActionLabel = audioProjection
    ? currentProgress > 0 ? copy.resume : copy.start
    : activeMedia?.primaryAction?.label ?? (currentProgress > 0 ? copy.resume : copy.start);
  const PrimaryActionIcon = currentTab === 'AUDIOBOOK' ? Headphones : currentTab === 'COMIC' ? Images : BookOpen;

  function replaceDetailDeepLink(tab: WorkDetailTabKey, editionId: string | null) {
    const nextSearch = new URLSearchParams(searchParams.toString());
    nextSearch.set('detailTab', tab);
    if (editionId) nextSearch.set('editionId', editionId);
    else nextSearch.delete('editionId');
    localDetailQueryRef.current = `${bookId}:${tab}:${editionId ?? ''}`;
    router.replace(`/works/${encodeURIComponent(bookId)}?${nextSearch.toString()}`, { scroll: false });
  }

  function selectDetailTab(tab: WorkDetailTabKey) {
    if (tab === currentTab) return;
    detailRequestRef.current?.abort();
    const edition = selectedEditionForDetailTab(book!, tab, null);
    setActiveTab(tab);
    setSelectedEditionId(edition?.id ?? null);
    setSelectedVolumeId(null);
    setChapterPage(1);
    setReadingUnits([]);
    setReadingUnitsPage(emptyReadingUnitsPage);
    setVolumeSections([]);
    setChapterLoading(true);
    setActiveMedia(legacyActiveMedia(book!, tab, edition?.id ?? null, [], []));
    setManageStructure(false);
    setKindleSendOpen(false);
    rememberDetailTab(bookId, tab);
    replaceDetailDeepLink(tab, edition?.id ?? null);

    preferenceRequestRef.current?.abort();
    const controller = new AbortController();
    preferenceRequestRef.current = controller;
    void apiV2Fetch(`/api/v2/catalog/works/${bookId}/detail-preference`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selectedTab: tab }),
      signal: controller.signal,
      keepalive: true
    }).then(async (response) => {
      if (response.status === 404 || response.status === 405) return;
      const payload = (await response.json()) as { ok: boolean; error?: { message?: string } };
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '记忆选项卡失败');
    }).catch((reason) => {
      if (reason instanceof DOMException && reason.name === 'AbortError') return;
      toast.error('没有保存详情页偏好', reason instanceof Error ? reason.message : '下次打开时可能不会恢复此选项卡');
    });
  }

  function handleDetailTabKeyDown(event: ReactKeyboardEvent<HTMLButtonElement>, tab: WorkDetailTabKey) {
    const currentIndex = detailTabs.findIndex((candidate) => candidate.key === tab);
    if (currentIndex < 0) return;
    let nextIndex: number | null = null;
    if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % detailTabs.length;
    if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + detailTabs.length) % detailTabs.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = detailTabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const nextTab = detailTabs[nextIndex]?.key;
    if (!nextTab) return;
    selectDetailTab(nextTab);
    window.requestAnimationFrame(() => document.getElementById(`work-detail-tab-${nextTab.toLowerCase()}`)?.focus());
  }

  function selectMediaEdition(editionId: string) {
    if (editionId === selectedEdition?.id) return;
    setSelectedEditionId(editionId);
    setSelectedVolumeId(null);
    setChapterPage(1);
    setReadingUnits([]);
    setReadingUnitsPage(emptyReadingUnitsPage);
    setVolumeSections([]);
    setChapterLoading(true);
    setActiveMedia(legacyActiveMedia(book!, currentTab, editionId, [], []));
    replaceDetailDeepLink(currentTab, editionId);
  }

  function startAudioEdition(editionId: string, chapterId?: string, chapterTitle?: string, volumeId?: string | null) {
    const alreadyLoaded = audioPlayback.bootstrap?.edition.id === editionId
      && audioPlayback.bootstrap.edition.workId === book!.id
      && (!volumeId || audioPlayback.bootstrap.volumeId === volumeId);
    if (chapterId && alreadyLoaded) {
      audioPlayback.selectChapter(chapterId, true);
    } else {
      void audioPlayback.loadEdition(editionId, {
        autoplay: true,
        volumeId,
        chapterId: chapterId && !alreadyLoaded ? chapterId : undefined,
        summary: {
          editionId,
          workId: book!.id,
          title: book!.title,
          author: book!.author === '未知作者' ? null : book!.author,
          coverUrl: book!.coverUrl,
          versionName: book!.editions.find((edition) => edition.id === editionId)?.versionName ?? null,
          narrator: book!.editions.find((edition) => edition.id === editionId)?.narrator ?? null,
          chapterTitle: chapterTitle ?? null
        }
      });
    }
  }

  function openEdition(edition: WorkView['editions'][number]) {
    const destination = readerUrlForEdition(edition);
    if (!destination) {
      toast.info('当前格式暂不可阅读', '请先将原始文件转换为 EPUB。');
      return;
    }
    if (mediaKindForEdition(edition) === 'AUDIOBOOK') startAudioEdition(edition.id);
    else router.push(destination);
  }

  function selectChapterVolume(volumeId: string) {
    setSelectedVolumeId(volumeId);
    setChapterPage(1);
    setReadingUnits([]);
    setChapterLoading(true);
  }

  const menuItemClass = 'flex min-h-10 w-full items-center gap-3 rounded-xl px-3 text-left text-sm text-stone-700 transition hover:bg-stone-100 hover:text-stone-950 disabled:cursor-not-allowed disabled:opacity-50';

  return (
    <div className="mx-auto w-full max-w-[1480px] pb-10 text-stone-900">
      <div className="mb-5 flex items-center gap-3">
        <MobileNavigationTrigger />
        <button
          type="button"
          onClick={() => router.push('/library')}
          className="flex min-h-11 items-center gap-2 rounded-xl px-2 text-sm text-stone-500 transition hover:bg-black/[0.035] hover:text-stone-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]"
        >
          <ChevronLeft size={17} /> <I18nText>返回全部图书</I18nText></button>
      </div>

      {error ? <div className="mb-4 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      <section className="rounded-[22px] border border-[#f1ddd3] bg-[#fffaf7] p-5 sm:p-6">
        <div className="grid gap-6 lg:grid-cols-[190px_minmax(0,1fr)] xl:grid-cols-[190px_minmax(0,1fr)_230px]">
          <Cover book={displayBook} className="aspect-[2/3] w-36 rounded-xl shadow-md sm:w-[190px]" size="large" priority />

          <div className="flex min-w-0 flex-col py-1 lg:h-[285px]">
            <h1
              data-i18n-skip
              className="line-clamp-2 text-3xl font-semibold leading-[1.15] tracking-tight text-stone-950 sm:text-[34px]"
              title={book.title}
            >
              {book.title}
            </h1>
            {currentTab === 'AUDIOBOOK' ? (
              <div className="mt-3 text-stone-600">
                <div data-i18n-skip className="text-base">{book.author}</div>
                {activeMedia?.narrator || selectedEdition?.narrator ? (
                  <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
                    <span className="text-stone-500"><I18nText>演播 </I18nText><span data-i18n-skip>{activeMedia?.narrator || selectedEdition?.narrator}</span></span>
                  </div>
                ) : null}
              </div>
            ) : (
              <div data-i18n-skip className="mt-3 text-base text-stone-600" data-testid="work-detail-header-meta">{book.author}</div>
            )}
            {book.desc !== DEFAULT_DESCRIPTION ? (
              <p
                data-i18n-skip
                className="mt-5 line-clamp-3 max-w-3xl whitespace-pre-line text-sm leading-7 text-stone-600"
                title={book.desc}
              >
                {book.desc}
              </p>
            ) : null}

            {currentTab !== 'STRUCTURE' ? <div className="mt-7 max-w-3xl lg:mt-auto">
              <div className="flex items-center gap-4">
                <span className="shrink-0 text-sm font-medium text-stone-700">{copy.progress}</span>
                <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-stone-200">
                  <div className="h-full rounded-full bg-[#ff4f26] transition-[width]" style={{ width: `${Math.max(0, Math.min(100, currentProgress))}%` }} />
                </div>
                <span className="w-11 text-right text-sm font-medium tabular-nums text-stone-700">{Math.round(currentProgress)}%</span>
              </div>
              <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
                <span className="font-medium text-stone-700">{copy.position}</span>
                <span className="text-stone-800">{currentPosition}</span>
              </div>
              {currentTab === 'AUDIOBOOK' && (activeMedia?.durationMs || selectedEdition?.durationMs) ? (
                <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-stone-500">
                  {formatDuration(activeMedia?.durationMs ?? selectedEdition?.durationMs) ? <span><I18nText>总时长 </I18nText>{formatDuration(activeMedia?.durationMs ?? selectedEdition?.durationMs)}</span> : null}
                </div>
              ) : null}
            </div> : null}
          </div>

          <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-end lg:col-start-2 xl:col-start-3 xl:flex-col xl:justify-end">
            {currentTab !== 'STRUCTURE' ? <Button
              disabled={!readerEditionId || !readerUrl}
              icon={PrimaryActionIcon}
              onClick={() => {
                if (!readerUrl) return;
                if (currentTab === 'AUDIOBOOK' && readerEditionId) startAudioEdition(readerEditionId, undefined, undefined, activeVolumeId);
                else router.push(readerUrl);
              }}
              className="!h-12 !min-h-12 w-full !rounded-xl !bg-[#ff4f26] !px-8 !text-base !text-white hover:!bg-[#e84420] sm:flex-1 xl:!flex-none xl:w-full"
            >
              {primaryActionLabel}
            </Button> : null}
            <div className="flex w-full gap-2 xl:justify-end">
              {currentTab !== 'STRUCTURE' ? <Select
                value={effectiveReadingStatus}
                options={currentStatusOptions}
                onChange={(status) => void updateReadingStatus(status)}
                ariaLabel={copy.status}
                align="right"
                className={cn('min-w-0 flex-1 xl:min-w-[150px]', busyAction === 'status' && 'pointer-events-none opacity-60')}
                triggerClassName="!rounded-xl !border-[#ead8cf] !bg-white/80 !shadow-none hover:!border-orange-200"
                menuClassName="!rounded-xl !border-[#ead8cf]"
              /> : null}
              {canManageSystem || currentTab !== 'STRUCTURE' ? <div ref={actionsRef} className="relative">
                <button
                  type="button"
                  onClick={() => setActionsOpen((open) => !open)}
                  className="flex h-11 w-12 items-center justify-center rounded-xl border border-[#ead8cf] bg-white/80 text-stone-600 transition hover:border-orange-200 hover:bg-white hover:text-stone-950"
                  aria-label={i18nAttribute("更多图书操作")}
                  aria-haspopup="menu"
                  aria-expanded={actionsOpen}
                >
                  <Ellipsis size={20} />
                </button>
                {actionsOpen ? (
                  <div role="menu" className="absolute right-0 top-full z-40 mt-2 w-60 rounded-2xl border border-stone-200 bg-white p-2 shadow-xl shadow-stone-900/10">
                    {canManageSystem ? <>
                      <button type="button" className={menuItemClass} onClick={() => { setActionsOpen(false); setEditingScope('work'); setEditing((value) => !value); }}>
                        <Edit3 size={16} /> <I18nText>编辑信息</I18nText></button>
                      <button type="button" className={menuItemClass} onClick={() => { setActionsOpen(false); setMetadataLookupOpen(true); }}>
                        <Database size={16} /> <I18nText>元数据识别</I18nText></button>
                      <button type="button" className={menuItemClass} disabled={saving} onClick={() => { setActionsOpen(false); coverInputRef.current?.click(); }}>
                        <ImageUp size={16} /> <I18nText>上传自定义封面</I18nText></button>
                    </> : null}
                    {currentTab !== 'AUDIOBOOK' ? (
                      <button type="button" className={menuItemClass} disabled={!selectedEdition?.id} onClick={() => { setActionsOpen(false); downloadPrimaryEdition(); }}>
                        <Download size={16} /> <I18nText>下载当前版本</I18nText></button>
                    ) : null}
                    {currentTab === 'EBOOK' ? <button type="button" className={menuItemClass} onClick={() => { setActionsOpen(false); setKindleSendOpen(true); }}>
                      <Send size={16} /> <I18nText>发送到 Kindle</I18nText></button> : null}
                    {canManageSystem ? <>
                      <div className="my-2 h-px bg-stone-100" />
                      {book.ignored ? (
                        <button type="button" className={menuItemClass} disabled={saving} onClick={() => { setActionsOpen(false); void setIgnored(false); }}>
                          <EyeOff size={16} /> <I18nText>恢复显示</I18nText></button>
                      ) : (
                        <button type="button" className={menuItemClass} disabled={saving} onClick={() => { setActionsOpen(false); void setIgnored(true); }}>
                          <EyeOff size={16} /> <I18nText>从书库隐藏</I18nText></button>
                      )}
                      <button type="button" className={cn(menuItemClass, 'text-red-600 hover:bg-red-50 hover:text-red-700')} disabled={saving} onClick={() => { setActionsOpen(false); setDeleteSource(false); setDangerActionOpen(true); }}>
                        <Trash2 size={16} /> <I18nText>删除记录</I18nText></button>
                    </> : null}
                  </div>
                ) : null}
              </div> : null}
            </div>
          </div>
        </div>
      </section>

      {canManageSystem ? <input
        ref={coverInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        className="hidden"
        onChange={(event) => {
          void uploadCover(event.target.files?.[0] ?? null);
          event.currentTarget.value = '';
        }}
      /> : null}

      {message ? <div className="mt-4 text-sm text-emerald-600">{message}</div> : null}

      {canManageSystem && editing ? (
        <section id="work-metadata-editor" className="mt-5 rounded-[22px] border border-stone-200 bg-white p-5 sm:p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-stone-950"><I18nText>编辑元数据</I18nText></h2>
              <p className="mt-1 text-sm text-stone-500"><I18nText>作品信息用于所有版本；版本信息记录出版社、ISBN、语言与版本说明。</I18nText></p>
            </div>
            <button type="button" onClick={() => setEditing(false)} className="flex h-9 w-9 items-center justify-center rounded-xl text-stone-500 hover:bg-stone-100" aria-label={i18nAttribute("关闭编辑")}>
              <X size={18} />
            </button>
          </div>
          <div className="mt-5 inline-flex rounded-xl bg-stone-100 p-1">
            <button type="button" onClick={() => setEditingScope('work')} className={cn('rounded-lg px-4 py-2 text-sm', editingScope === 'work' ? 'bg-white font-medium text-[#e84420] shadow-sm' : 'text-stone-600')}><I18nText>作品信息</I18nText></button>
            <button type="button" onClick={() => { const edition = book.editions.find((item) => item.id === (editingEditionId ?? selectedEdition?.id)) ?? selectedEdition ?? book.editions[0]; if (edition) editEdition(edition); }} className={cn('rounded-lg px-4 py-2 text-sm', editingScope === 'edition' ? 'bg-white font-medium text-[#e84420] shadow-sm' : 'text-stone-600')}><I18nText>版本信息</I18nText></button>
          </div>
          {editingScope === 'work' ? <div className="mt-5 grid gap-4 md:grid-cols-2">
            <label className="text-sm text-stone-600"><I18nText>标题</I18nText><input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} className={inputClassName()} /></label>
            <label className="text-sm text-stone-600"><I18nText>作者</I18nText><input value={form.author} onChange={(event) => setForm({ ...form, author: event.target.value })} className={inputClassName()} /></label>
            {currentTab !== 'STRUCTURE' ? <label className="text-sm text-stone-600">
              {copy.status}
              <Select value={form.status} options={currentStatusOptions} onChange={(status) => setForm({ ...form, status })} ariaLabel={copy.status} className="mt-2 w-full" triggerClassName="!rounded-xl !border-stone-200 !shadow-none" />
            </label> : null}
            <label className="text-sm text-stone-600"><I18nText>出版年</I18nText><input value={form.publishedYear} onChange={(event) => setForm({ ...form, publishedYear: event.target.value })} type="number" min="1000" max="3000" className={inputClassName()} /></label>
            <label className="text-sm text-stone-600"><I18nText>系列名</I18nText><input value={form.seriesName} onChange={(event) => setForm({ ...form, seriesName: event.target.value })} className={inputClassName()} /></label>
            <label className="text-sm text-stone-600"><I18nText>系列序号</I18nText><input value={form.seriesIndex} onChange={(event) => setForm({ ...form, seriesIndex: event.target.value })} type="number" step="0.01" className={inputClassName()} /></label>
            <label className="text-sm text-stone-600 md:col-span-2"><I18nText>标签</I18nText><input value={form.tags} onChange={(event) => setForm({ ...form, tags: event.target.value })} placeholder={i18nAttribute("标签，用逗号分隔")} className={inputClassName()} /></label>
            <label className="text-sm text-stone-600 md:col-span-2"><I18nText>简介</I18nText><textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} rows={5} className="mt-2 w-full rounded-xl border border-stone-200 bg-white px-4 py-3 text-stone-900 outline-none transition focus:border-orange-300 focus:ring-4 focus:ring-orange-100/70" /></label>
          </div> : <div className="mt-5 grid gap-4 md:grid-cols-2">
            <label className="text-sm text-stone-600 md:col-span-2"><I18nText>编辑版本</I18nText><Select value={editingEditionId ?? ''} options={book.editions.map((edition) => ({ value: edition.id, label: `${edition.versionName} · ${edition.format}` }))} onChange={(id) => { const edition = book.editions.find((item) => item.id === id); if (edition) editEdition(edition); }} ariaLabel={i18nAttribute("编辑版本")} className="mt-2 w-full" /></label>
            <label className="text-sm text-stone-600"><I18nText>版本名称</I18nText><input value={editionForm.versionName} onChange={(event) => setEditionForm({ ...editionForm, versionName: event.target.value })} className={inputClassName()} /></label>
            <label className="text-sm text-stone-600"><I18nText>出版社</I18nText><input value={editionForm.publisher} onChange={(event) => setEditionForm({ ...editionForm, publisher: event.target.value })} className={inputClassName()} /></label>
            <label className="text-sm text-stone-600"><I18nText>出版日期</I18nText><input type="date" value={editionForm.publishedAt} onChange={(event) => setEditionForm({ ...editionForm, publishedAt: event.target.value })} className={inputClassName()} /></label>
            <label className="text-sm text-stone-600"><I18nText>语言</I18nText><input value={editionForm.language} onChange={(event) => setEditionForm({ ...editionForm, language: event.target.value })} placeholder={i18nAttribute("例如 zh-CN")} className={inputClassName()} /></label>
            <label className="text-sm text-stone-600">ISBN<input value={editionForm.isbn} onChange={(event) => setEditionForm({ ...editionForm, isbn: event.target.value })} className={inputClassName()} /></label>
            <label className="text-sm text-stone-600"><I18nText>其他标识符</I18nText><input value={editionForm.identifier} onChange={(event) => setEditionForm({ ...editionForm, identifier: event.target.value })} className={inputClassName()} /></label>
            {book.editions.find((edition) => edition.id === editingEditionId)?.mediaKind === 'AUDIOBOOK' ? <label className="text-sm text-stone-600 md:col-span-2"><I18nText>演播者</I18nText><input value={editionForm.narrator} onChange={(event) => setEditionForm({ ...editionForm, narrator: event.target.value })} className={inputClassName()} /></label> : null}
            <label className="text-sm text-stone-600 md:col-span-2"><I18nText>版本说明</I18nText><textarea value={editionForm.description} onChange={(event) => setEditionForm({ ...editionForm, description: event.target.value })} rows={4} className="mt-2 w-full rounded-xl border border-stone-200 bg-white px-4 py-3 outline-none focus:border-orange-300" /></label>
          </div>}
          <div className="mt-5 flex justify-end gap-3">
            <Button variant="secondary" className="!rounded-xl" onClick={() => setEditing(false)}><I18nText>取消</I18nText></Button>
            <Button loading={busyAction === (editingScope === 'work' ? 'saveMetadata' : 'saveEditionMetadata')} loadingText={i18nAttribute("保存中")} disabled={saving} icon={Save} onClick={() => void (editingScope === 'work' ? saveMetadata() : saveEditionMetadata())} className="!rounded-xl !bg-[#ff4f26] !text-white hover:!bg-[#e84420]"><I18nText>保存信息</I18nText></Button>
          </div>
        </section>
      ) : null}

      <div className="mt-6 overflow-x-auto">
        <div className="inline-flex min-w-full gap-9 border-b border-stone-200 sm:min-w-0" role="tablist" aria-label={i18nAttribute("图书内容版本")}>
          {detailTabs.map((tab) => {
            const selected = tab.key === currentTab;
            return (
              <button
                key={tab.key}
                id={`work-detail-tab-${tab.key.toLowerCase()}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`work-detail-panel-${tab.key.toLowerCase()}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => selectDetailTab(tab.key)}
                onKeyDown={(event) => handleDetailTabKeyDown(event, tab.key)}
                className={cn(
                  'relative flex min-h-14 shrink-0 items-center justify-center px-0.5 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ff4f26] focus-visible:ring-offset-4',
                  selected ? 'text-stone-950' : 'text-stone-500 hover:text-stone-950'
                )}
              >
                <span>{i18nAttribute(tab.label)}</span>
                {selected ? <span className="absolute inset-x-0 -bottom-px h-0.5 bg-[#ff4f26]" /> : null}
              </button>
            );
          })}
        </div>
      </div>

      {currentTab !== 'STRUCTURE' ? (
        <div>
          <section id={`work-detail-panel-${currentTab.toLowerCase()}`} role="tabpanel" aria-labelledby={`work-detail-tab-${currentTab.toLowerCase()}`} className="py-6">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-stone-950">{hasAudioNavigation ? i18nAttribute("音频章节") : hasChapterNavigation ? i18nAttribute("章节") : hasVolumeSections ? i18nAttribute("卷册") : i18nAttribute("阅读内容")}</h2>
                <p className="mt-1 text-sm text-stone-500">
                  {hasAudioNavigation
                    ? readingUnitsPage.total > 0
                      ? i18nAttribute("共 {value0} 章{value1}", { value0: readingUnitsPage.total, value1: formatDuration(activeMedia?.durationMs ?? selectedEdition?.durationMs) ? ` · ${formatDuration(activeMedia?.durationMs ?? selectedEdition?.durationMs)}` : '' })
                      : i18nAttribute("打开播放器查看音轨与章节")
                    : hasChapterNavigation
                    ? readingUnitsPage.total > 0 ? i18nAttribute("共 {value0} 章", { value0: readingUnitsPage.total }) : i18nAttribute("未解析章节")
                    : !selectedEdition?.readable ? i18nAttribute("{value0} 格式已入库，转换为 EPUB 后可阅读", { value0: selectedEdition?.formatValue ?? '该' })
                    : hasVolumeSections ? i18nAttribute("{value0} 个卷册", { value0: volumeSections.length }) : i18nAttribute("打开阅读器查看内容")}
                </p>
              </div>
              <div className="flex flex-wrap items-center justify-end gap-2">
                {mediaEditions.length > 1 ? (
                  <Select
                    value={selectedEdition?.id ?? ''}
                    options={mediaEditions.map((edition) => ({ value: edition.id, label: edition.versionName }))}
                    onChange={selectMediaEdition}
                    ariaLabel={i18nAttribute("选择{value0}版本", { value0: i18nAttribute(detailTabs.find((tab) => tab.key === currentTab)?.label ?? '当前媒介') })}
                    className="min-w-[190px]"
                    triggerClassName="!rounded-xl !border-[#ead8cf] !shadow-none"
                  />
                ) : null}
                {(hasChapterNavigation || hasAudioNavigation) && hasVolumeSections ? (
                  <VolumeSelect
                    items={volumeSections.map((volume) => ({ id: volume.id, title: volume.title }))}
                    value={activeVolumeId}
                    onChange={selectChapterVolume}
                    disabled={chapterLoading}
                    className="w-full min-w-[260px] sm:w-[360px]"
                  />
                ) : null}
              </div>
            </div>

            <div className="mt-4">
              {chapterLoading && readingUnits.length === 0 && (hasChapterNavigation || hasAudioNavigation || volumeSections.length === 0) ? (
                <div className="rounded-xl border border-stone-100 bg-stone-50 px-4 py-5 text-sm text-stone-500" role="status" aria-live="polite">
                  <I18nText>正在切换到</I18nText>{detailTabs.find((tab) => tab.key === currentTab)?.label ?? i18nAttribute("所选版本")}…
                </div>
              ) : hasAudioNavigation && readingUnits.length > 0 ? (
                <div className={cn('divide-y divide-stone-100 border-y border-stone-100 transition', chapterLoading && 'opacity-65')} aria-busy={chapterLoading || undefined}>
                  {readingUnits.map((unit, index) => {
                    const current = audioProjection
                      ? audioProjection.currentChapterId === unit.id
                        || Boolean(
                          audioProjection.currentFileId
                          && audioProjection.currentFileId === unit.fileId
                          && audioProjection.currentChapterStartMs !== null
                          && Math.abs(audioProjection.currentChapterStartMs - (unit.startMs ?? 0)) < 500
                        )
                      : unit.current
                        || activeMedia?.currentUnitId === unit.id
                        || Boolean(activeMedia?.positionLabel && activeMedia.positionLabel !== '未开始' && activeMedia.positionLabel.startsWith(unit.title));
                    const duration = unit.durationMs ?? ((unit.endMs ?? 0) > (unit.startMs ?? 0) ? (unit.endMs ?? 0) - (unit.startMs ?? 0) : null);
                    const displayIndex = (readingUnitsPage.page - 1) * readingUnitsPage.pageSize + index + 1;
                    return (
                      <button
                        key={unit.id}
                        type="button"
                        disabled={!readerEditionId}
                        onClick={() => readerEditionId && startAudioEdition(readerEditionId, unit.id, unit.title, activeVolumeId)}
                        className={cn(
                          'grid min-h-14 w-full grid-cols-[42px_minmax(0,1fr)_72px_28px] items-center gap-3 px-2 text-left text-sm transition disabled:cursor-not-allowed disabled:opacity-50 sm:grid-cols-[48px_minmax(0,1fr)_100px_28px]',
                          current ? 'bg-[#fff4ef] text-[#e84420]' : 'hover:bg-stone-50'
                        )}
                      >
                        <span className="tabular-nums text-stone-500">{String(displayIndex).padStart(2, '0')}</span>
                        <span className={cn('truncate font-medium', current ? 'text-[#e84420]' : 'text-stone-800')}>{unit.title}</span>
                        <span className={cn('text-right text-xs tabular-nums', current ? 'text-[#e84420]' : 'text-stone-400')}>{formatDuration(duration) || '—'}</span>
                        {current ? <Headphones size={18} className="text-[#ff4f26]" /> : <Play size={16} className="text-stone-400" />}
                      </button>
                    );
                  })}
                </div>
              ) : hasChapterNavigation && readingUnits.length > 0 ? (
                <div className={cn('divide-y divide-stone-100 border-y border-stone-100 transition', chapterLoading && 'opacity-65')} aria-busy={chapterLoading || undefined}>
                  {readingUnits.map((unit, index) => {
                    const state = chapterStates[index];
                    const chapterUrl = readerUrlForChapter(book, readerEditionId, activeVolumeId, unit.href);
                    const displayIndex = (readingUnitsPage.page - 1) * readingUnitsPage.pageSize + index + 1;
                    return (
                      <button key={unit.id} type="button" disabled={!chapterUrl} onClick={() => chapterUrl && router.push(chapterUrl)} className={cn('grid min-h-14 w-full grid-cols-[48px_minmax(0,1fr)_100px_28px] items-center gap-3 px-1 text-left text-sm transition disabled:cursor-not-allowed disabled:opacity-50', state === 'current' ? 'bg-[#fff4ef] text-[#e84420]' : 'hover:bg-stone-50')}>
                        <span className="tabular-nums text-stone-500">{displayIndex}</span>
                        <span className={cn('truncate font-medium', state === 'current' ? 'text-[#e84420]' : 'text-stone-800')}>{unit.title}</span>
                        <span className={cn('text-xs', state === 'current' ? 'text-[#e84420]' : 'text-stone-400')}>{state === 'current' ? i18nAttribute("正在阅读") : state === 'read' ? i18nAttribute("已读") : i18nAttribute("未读")}</span>
                        {state === 'current' ? <BarChart3 size={18} className="text-[#ff4f26]" /> : state === 'read' ? <CheckCircle2 size={18} className="text-stone-400" /> : <Circle size={18} className="text-stone-400" />}
                      </button>
                    );
                  })}
                </div>
              ) : hasVolumeSections && !hasChapterNavigation && !hasAudioNavigation ? (
                <div className="grid grid-cols-[repeat(auto-fill,minmax(130px,160px))] gap-5">
                  {volumeSections.map((volume, index) => (
                    <button key={volume.id} type="button" disabled={!readerEditionId} onClick={() => readerEditionId && router.push(`/reader/${readerEditionId}?volume=${encodeURIComponent(volume.id)}`)} className="group text-left disabled:cursor-not-allowed disabled:opacity-50">
                      <div className="relative overflow-hidden rounded-xl bg-stone-100 shadow-sm transition group-hover:-translate-y-0.5 group-hover:shadow-md">
                        <Cover
                          book={{
                            id: volume.id,
                            title: volume.title,
                            author: book.author,
                            format: selectedEdition?.format ?? book.format,
                            gradient: book.gradient,
                            coverUrl: volume.coverUrl
                          }}
                          className="aspect-[2/3] w-full rounded-none"
                          size="small"
                        />
                        <span className="absolute left-2 top-2 rounded-full bg-white/90 px-2 py-0.5 text-[11px] tabular-nums text-stone-600 shadow-sm">{String(index + 1).padStart(2, '0')}</span>
                      </div>
                      <span className="mt-2 block line-clamp-2 text-sm font-medium leading-5 text-stone-900">{volume.title}</span>
                    </button>
                  ))}
                </div>
              ) : selectedEdition && !selectedEdition.readable ? (
                <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-900">
                  <span><I18nText>原始 </I18nText>{selectedEdition.formatValue} <I18nText>文件已安全入库，当前阅读器暂不支持直接打开。</I18nText></span>
                  {canManageSystem && selectedEdition.conversionAvailable ? <Button loading={busyAction === `convert:${selectedEdition.id}`} disabled={saving && busyAction !== `convert:${selectedEdition.id}`} onClick={() => void convertEdition(selectedEdition)} className="!rounded-xl !bg-[#ff4f26] !text-white hover:!bg-[#e84420]"><I18nText>转换为 EPUB</I18nText></Button> : null}
                </div>
              ) : (
                <button type="button" disabled={!readerUrl} onClick={() => {
                  if (!readerUrl) return;
                  if (hasAudioNavigation && readerEditionId) startAudioEdition(readerEditionId, undefined, undefined, activeVolumeId);
                  else router.push(readerUrl);
                }} className="flex w-full items-center justify-between rounded-xl border border-stone-200 px-4 py-4 text-left text-sm text-stone-600 transition hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50">
                  <span>{hasAudioNavigation ? i18nAttribute("打开迷你播放器查看音轨与章节") : i18nAttribute("在阅读器中查看内容")}</span><ChevronRight size={17} />
                </button>
              )}

              {(hasChapterNavigation || hasAudioNavigation) && readingUnitsPage.total > 0 ? (
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-stone-500">
                  <span><I18nText>第 </I18nText>{readingUnitsPage.page} / {readingUnitsPage.totalPages} <I18nText>页</I18nText></span>
                  <div className="flex gap-2">
                    <Button variant="secondary" className="!min-h-9 !rounded-xl !px-3 !py-1.5" disabled={chapterLoading || readingUnitsPage.page <= 1} onClick={() => setChapterPage((current) => Math.max(1, current - 1))}><I18nText>上一页</I18nText></Button>
                    <Button variant="secondary" className="!min-h-9 !rounded-xl !px-3 !py-1.5" disabled={chapterLoading || readingUnitsPage.page >= readingUnitsPage.totalPages} onClick={() => setChapterPage((current) => Math.min(readingUnitsPage.totalPages, current + 1))}><I18nText>下一页</I18nText></Button>
                  </div>
                </div>
              ) : null}
            </div>
          </section>
        </div>
      ) : (
        <div id="work-detail-panel-structure" role="tabpanel" aria-labelledby="work-detail-tab-structure" className="space-y-8 py-6">
          <section>
            <div className="flex items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-stone-950"><I18nText>系列</I18nText></h2>
                <p className="mt-1 text-sm text-stone-500">
                  {book.seriesName ? (book.seriesIndex !== null ? i18nAttribute('{value0} · 第 {value1} 部', { value0: book.seriesName, value1: book.seriesIndex }) : book.seriesName) : i18nAttribute("尚未归入系列，可通过“编辑信息”补充。")}
                </p>
              </div>
              {book.seriesName && seriesTotal > 0 ? (
                <div className="flex items-center gap-3">
                  <span className="text-sm text-stone-400">{seriesTotal} <I18nText>本</I18nText></span>
                  <div className="flex items-center gap-1" aria-label={i18nAttribute("浏览系列图书")}>
                    <button type="button" disabled={!seriesCanScrollLeft} onClick={() => scrollSeries(-1)} className="flex h-9 w-9 items-center justify-center rounded-lg border border-stone-200 text-stone-600 transition hover:border-orange-200 hover:text-[#e84420] disabled:cursor-not-allowed disabled:opacity-35" aria-label={i18nAttribute("向左浏览系列")}><ChevronLeft size={17} /></button>
                    <button type="button" disabled={!seriesCanScrollRight} onClick={() => scrollSeries(1)} className="flex h-9 w-9 items-center justify-center rounded-lg border border-stone-200 text-stone-600 transition hover:border-orange-200 hover:text-[#e84420] disabled:cursor-not-allowed disabled:opacity-35" aria-label={i18nAttribute("向右浏览系列")}><ChevronRight size={17} /></button>
                  </div>
                  <button type="button" onClick={() => router.push(`/library?seriesName=${encodeURIComponent(book.seriesName ?? '')}`)} className="text-sm font-medium text-[#ED4D2D] hover:text-[#C83B23]"><I18nText>查看全部</I18nText></button>
                </div>
              ) : null}
            </div>
            {book.seriesName && seriesLoading ? <div className="mt-4 text-sm text-stone-400"><I18nText>正在读取系列...</I18nText></div> : null}
            {book.seriesName && !seriesLoading && seriesBooks.length > 0 ? (
              <div
                ref={seriesScrollerRef}
                className="mt-4 flex cursor-grab snap-x snap-proximity gap-6 overflow-x-auto overscroll-x-contain border-y border-stone-100 py-4 active:cursor-grabbing"
                tabIndex={0}
                aria-label={i18nAttribute("系列图书列表")}
                onScroll={updateSeriesScrollState}
                onPointerDown={startSeriesDrag}
                onPointerMove={moveSeriesDrag}
                onPointerUp={finishSeriesDrag}
                onPointerCancel={finishSeriesDrag}
                onKeyDown={(event) => {
                  if (event.key === 'ArrowLeft') { event.preventDefault(); scrollSeries(-1); }
                  if (event.key === 'ArrowRight') { event.preventDefault(); scrollSeries(1); }
                }}
              >
                {seriesBooks.map((seriesBook) => {
                  const current = seriesBook.id === book.id;
                  return (
                    <button
                      key={seriesBook.id}
                      type="button"
                      data-series-current={current ? 'true' : undefined}
                      onClick={() => !suppressSeriesClickRef.current && !current && router.push(workDetailTabHref(seriesBook.id, 'STRUCTURE'))}
                      className="group w-44 shrink-0 snap-start text-left"
                      aria-current={current ? 'page' : undefined}
                    >
                      <div className={cn('flex items-center gap-3 rounded-xl p-1.5 transition', current ? 'bg-[#fff4ef]' : 'hover:bg-stone-50')}>
                        <Cover book={seriesBook} className="aspect-[2/3] w-16 shrink-0 rounded-lg" size="small" />
                        <div className="min-w-0">
                          <div className="line-clamp-2 text-sm font-medium leading-5 text-stone-900">{seriesBook.title}</div>
                          <div className="mt-1 truncate text-xs text-stone-500">{seriesBook.author}</div>
                        </div>
                      </div>
                      <div className={cn('mx-1 mt-2 h-0.5 rounded-full transition', current ? 'bg-[#ff4f26]' : 'bg-transparent group-hover:bg-stone-200')} />
                    </button>
                  );
                })}
              </div>
            ) : null}
          </section>

          <section className="border-t border-stone-200 pt-8">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-stone-950"><I18nText>版本与内容</I18nText></h2>
                <p className="mt-1 text-sm text-stone-500">{book.versionCount} <I18nText>个版本 · 覆盖 </I18nText>{detailTabs.filter((tab) => tab.key !== 'STRUCTURE').length} <I18nText>种媒介。管理模式下可调整各媒介主版本和卷册位置。</I18nText></p>
              </div>
              {canManageSystem ? <Button variant={manageStructure ? 'secondary' : 'primary'} icon={Settings2} onClick={() => setManageStructure((value) => !value)} className={cn('!rounded-xl', !manageStructure && '!bg-[#ff4f26] !text-white hover:!bg-[#e84420]')}>
                {manageStructure ? i18nAttribute("完成管理") : i18nAttribute("管理内容结构")}
              </Button> : null}
            </div>

            <div className="mt-6 space-y-5">
            {book.editions.map((edition) => (
              <article key={edition.id} className={cn('rounded-2xl border bg-white', edition.primary || edition.id === book.primaryEditionId ? 'border-orange-200' : 'border-stone-200')}>
                <div className="flex flex-wrap items-center gap-4 p-4 sm:p-5">
                  <span className={cn('inline-flex min-w-16 justify-center rounded-lg border px-3 py-2 text-xs font-semibold', formatTone(edition.formatValue))}>{edition.formatValue}</span>
                  <div className="min-w-[220px] flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 data-i18n-skip className="font-semibold text-stone-950">{edition.versionName}</h3>
                      <span className="rounded-full bg-stone-100 px-2 py-0.5 text-[11px] font-medium text-stone-600">{mediaKindForEdition(edition) === 'AUDIOBOOK' ? i18nAttribute("有声书") : mediaKindForEdition(edition) === 'COMIC' ? i18nAttribute("漫画") : i18nAttribute("电子书")}</span>
                      {edition.primary || edition.id === book.primaryEditionId ? <span className="rounded-full bg-[#fff0e9] px-2 py-0.5 text-[11px] font-medium text-[#e84420]"><I18nText>媒介主版本</I18nText></span> : null}
                    </div>
                    <div className="mt-1 text-xs text-stone-500">{edition.size} · {editionUnitLabel(edition, i18nAttribute)} · {fileName(edition.files[0]?.path)}</div>
                    {!edition.readable ? <div className="mt-1 text-xs text-amber-700"><I18nText>原始文件已入库，转换为 EPUB 后可阅读</I18nText></div> : null}
                    {edition.conversion ? <div className="mt-1 text-xs text-[#B45336]"><I18nText>由 </I18nText>{edition.conversion.sourceFormat} <I18nText>自动转换为 </I18nText>{edition.conversion.targetFormat}</div> : null}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {edition.readable ? <Button variant="secondary" className="!min-h-9 !rounded-xl !px-3 !py-1.5" onClick={() => openEdition(edition)}>{mediaKindForEdition(edition) === 'AUDIOBOOK' ? i18nAttribute("收听") : mediaKindForEdition(edition) === 'COMIC' ? i18nAttribute("查看") : i18nAttribute("阅读")}</Button> : canManageSystem && edition.conversionAvailable ? <Button loading={busyAction === `convert:${edition.id}`} disabled={saving && busyAction !== `convert:${edition.id}`} variant="secondary" className="!min-h-9 !rounded-xl !px-3 !py-1.5" onClick={() => void convertEdition(edition)}><I18nText>转换为 EPUB</I18nText></Button> : <Button disabled variant="secondary" className="!min-h-9 !rounded-xl !px-3 !py-1.5"><I18nText>暂不支持阅读</I18nText></Button>}
                    {manageStructure ? <Button variant="ghost" className="!min-h-9 !rounded-xl !px-3 !py-1.5" onClick={() => editEdition(edition)}><I18nText>编辑版本</I18nText></Button> : null}
                    {manageStructure && !edition.primary && edition.id !== book.primaryEditionId ? (
                      <Button loading={busyAction === `primary:${edition.id}`} disabled={saving && busyAction !== `primary:${edition.id}`} variant="ghost" className="!min-h-9 !rounded-xl !px-3 !py-1.5" onClick={() => void postAction(`/api/v2/catalog/works/${book.id}/editions/${edition.id}/primary`, '已设为主版本', { refreshBook: true, busyKey: `primary:${edition.id}` })}>
                        <I18nText>设为主版本</I18nText></Button>
                    ) : null}
                    {manageStructure && book.editions.length > 1 ? <Button variant="ghost" className="!min-h-9 !rounded-xl !px-3 !py-1.5" onClick={() => { setSplitTarget(edition); setSplitForm({ title: `${book.title}（${edition.versionName}）`, author: book.author === '未知作者' ? '' : book.author, copyShelves: true }); }}><I18nText>拆分为作品</I18nText></Button> : null}
                  </div>
                </div>

                {edition.volumes.length > 0 ? (
                  <div className="border-t border-stone-100 px-4 py-2 sm:px-5">
                    {edition.volumes.map((volume, index) => (
                      <div key={volume.id} className="flex min-h-12 items-center gap-3 border-b border-stone-100 py-2 last:border-b-0">
                        <span className="w-8 text-xs tabular-nums text-stone-400">{String(index + 1).padStart(2, '0')}</span>
                        <span data-i18n-skip className="min-w-0 flex-1 truncate text-sm text-stone-800">{volume.title}</span>
                        <span className="text-xs text-stone-400">{volume.chapterCount ? i18nAttribute("{value0} 章", { value0: volume.chapterCount }) : volume.pageCount ? i18nAttribute("{value0} 页", { value0: volume.pageCount }) : ''}</span>
                        {manageStructure ? (
                          <div className="flex items-center gap-1">
                            <button type="button" disabled={saving || index === 0} onClick={() => void moveVolume(volume.id, 'up')} className="flex h-8 w-8 items-center justify-center rounded-lg text-stone-500 hover:bg-stone-100 disabled:opacity-30" aria-label={i18nAttribute("前移 {value0}", { value0: volume.title })}><ChevronLeft size={16} /></button>
                            <button type="button" disabled={saving || index === edition.volumes.length - 1} onClick={() => void moveVolume(volume.id, 'down')} className="flex h-8 w-8 items-center justify-center rounded-lg text-stone-500 hover:bg-stone-100 disabled:opacity-30" aria-label={i18nAttribute("后移 {value0}", { value0: volume.title })}><ChevronRight size={16} /></button>
                            <button type="button" disabled={saving} onClick={() => openMoveTarget(volume)} className="flex h-8 w-8 items-center justify-center rounded-lg text-stone-500 hover:bg-stone-100 disabled:opacity-30" aria-label={i18nAttribute("移动 {value0} 到其他图书", { value0: volume.title })}><MoveRight size={16} /></button>
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="border-t border-stone-100 px-5 py-3 text-sm text-stone-400"><I18nText>单文件版本，没有独立卷册。</I18nText></div>
                )}
              </article>
            ))}
            </div>
          </section>
        </div>
      )}

      {canManageSystem ? <MetadataLookupModal
        book={book}
        open={metadataLookupOpen}
        onClose={() => setMetadataLookupOpen(false)}
        onApplied={(nextBook) => {
          if (nextBook) setBook(nextBook);
          void loadBook();
          toast.success('元数据已应用');
        }}
      /> : null}

      <KindleSendModal
        book={book}
        open={kindleSendOpen}
        preferredEditionId={readerEditionId}
        onClose={() => setKindleSendOpen(false)}
      />

      {canManageSystem && splitTarget ? <div className="fixed inset-0 z-[95] flex items-end justify-center bg-stone-950/40 p-0 backdrop-blur-sm md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={i18nAttribute("拆分版本")}>
        <div className="w-full max-w-lg rounded-t-[26px] border border-stone-200 bg-white p-6 shadow-2xl md:rounded-[26px]">
          <div className="flex items-start justify-between gap-4"><div><h2 className="text-lg font-semibold text-stone-950"><I18nText>拆分为独立作品</I18nText></h2><p className="mt-2 text-sm leading-6 text-stone-600">{i18nAttribute('将“{value0}”及关联的阅读进度移到新作品，文件不会复制或删除。', { value0: splitTarget.versionName })}</p></div><button type="button" onClick={() => setSplitTarget(null)}><X size={18} /></button></div>
          <div className="mt-5 grid gap-4"><label className="text-sm text-stone-600"><I18nText>新作品标题</I18nText><input value={splitForm.title} onChange={(event) => setSplitForm({ ...splitForm, title: event.target.value })} className={inputClassName()} /></label><label className="text-sm text-stone-600"><I18nText>作者</I18nText><input value={splitForm.author} onChange={(event) => setSplitForm({ ...splitForm, author: event.target.value })} className={inputClassName()} /></label><label className="flex items-start gap-3 rounded-xl bg-stone-50 p-4 text-sm text-stone-700"><input type="checkbox" checked={splitForm.copyShelves} onChange={(event) => setSplitForm({ ...splitForm, copyShelves: event.target.checked })} className="mt-0.5 accent-[#ff4f26]" /><span><I18nText>复制原作品的普通书架归属</I18nText><span className="mt-1 block text-xs text-stone-500"><I18nText>智能书架会根据规则自动计算，无需复制。</I18nText></span></span></label></div>
          <div className="mt-6 flex justify-end gap-2"><Button variant="secondary" onClick={() => setSplitTarget(null)}><I18nText>取消</I18nText></Button><Button loading={busyAction === `split:${splitTarget.id}`} disabled={!splitForm.title.trim()} onClick={() => void splitSelectedEdition()}><I18nText>确认拆分</I18nText></Button></div>
        </div>
      </div> : null}

      {canManageSystem && moveTargetOpen && movingVolume ? (
        <div className="fixed inset-0 z-[90] flex items-end justify-center bg-stone-950/40 p-0 backdrop-blur-sm md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={i18nAttribute("转移图书内容")}>
          <div className="w-full max-w-2xl rounded-t-[26px] border border-stone-200 bg-white p-5 shadow-2xl md:rounded-[26px]">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-stone-950"><I18nText>转移图书内容</I18nText></h2>
                <p className="mt-2 text-sm leading-6 text-stone-600">{i18nAttribute('将「{value0}」及其内容按媒介和卷册结构转移到另一图书。', { value0: movingVolume.title })}</p>
              </div>
              <button type="button" onClick={() => setMoveTargetOpen(false)} className="flex h-10 w-10 items-center justify-center rounded-xl text-stone-500 hover:bg-stone-100" aria-label={i18nAttribute("关闭")}><X size={18} /></button>
            </div>
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <section>
                <label className="text-sm font-medium text-stone-700"><I18nText>目标图书</I18nText></label>
                <div className="mt-2 flex h-11 items-center gap-2 rounded-xl border border-stone-200 px-3">
                  <input value={targetSearch} onChange={(event) => setTargetSearch(event.target.value)} placeholder={i18nAttribute("搜索标题、作者或标签")} className="w-full bg-transparent text-sm outline-none" />
                </div>
                <div className="mt-3 max-h-72 space-y-2 overflow-auto pr-1">
                  {targetBooks.map((targetBook) => (
                    <button data-i18n-skip key={targetBook.id} type="button" onClick={() => { setTargetBookId(targetBook.id); setTargetEditionId(targetBook.editions.find((edition) => edition.id === targetBook.primaryEditionId)?.id ?? targetBook.editions[0]?.id ?? ''); }} className={cn('w-full rounded-xl border p-3 text-left transition', targetBook.id === targetBookId ? 'border-orange-200 bg-[#fff4ef]' : 'border-stone-100 bg-stone-50 hover:bg-stone-100')}>
                      <span className="block truncate text-sm font-medium text-stone-950">{targetBook.title}</span>
                      <span className="mt-1 block truncate text-xs text-stone-500">{targetBook.author} · {targetBook.versionCount} <I18nText>个版本</I18nText></span>
                    </button>
                  ))}
                  {targetBooksLoading ? <div className="rounded-xl bg-stone-50 p-3 text-sm text-stone-500"><I18nText>正在搜索...</I18nText></div> : null}
                  {!targetBooksLoading && targetBooks.length === 0 ? <div className="rounded-xl bg-stone-50 p-3 text-sm text-stone-500"><I18nText>没有找到可选图书。</I18nText></div> : null}
                </div>
              </section>
              <section>
                <div className="text-sm font-medium text-stone-700"><I18nText>目标图书内容</I18nText></div>
                <div className="mt-2 rounded-xl bg-stone-50 p-3 text-xs leading-5 text-stone-500"><I18nText>源格式：</I18nText>{movingEdition?.format ?? book.format}<I18nText>。不同媒介会并存；同格式且双方都有卷册时合并卷册，否则保留为独立版本。</I18nText></div>
                <div className="mt-3 max-h-72 space-y-2 overflow-auto pr-1">
                  {targetEditionOptions.map((edition) => {
                    return (
                      <div key={edition.id} className={cn('w-full rounded-xl border p-3', edition.primary ? 'border-orange-100 bg-[#fffaf7]' : 'border-stone-100 bg-white')}>
                        <span data-i18n-skip className="block truncate text-sm font-medium text-stone-950">{edition.versionName}</span>
                        <span className="mt-1 block text-xs text-stone-500">{edition.format} · {edition.volumes.length} <I18nText>个卷册 · </I18nText>{mediaKindForEdition(edition) === 'AUDIOBOOK' ? i18nAttribute("有声书") : mediaKindForEdition(edition) === 'COMIC' ? i18nAttribute("漫画") : i18nAttribute("电子书")}</span>
                      </div>
                    );
                  })}
                  {!selectedTargetBook ? <div className="rounded-xl bg-stone-50 p-3 text-sm text-stone-500"><I18nText>先选择一本目标图书。</I18nText></div> : null}
                </div>
              </section>
            </div>
            <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
              <div className="max-w-md text-sm text-stone-500">{selectedTargetEdition ? transferPreview : i18nAttribute("请选择目标图书")}</div>
              <div className="flex gap-2">
                <Button variant="secondary" className="!rounded-xl" onClick={() => setMoveTargetOpen(false)}><I18nText>取消</I18nText></Button>
                <Button loading={busyAction === `move-to:${movingVolume.id}`} loadingText={i18nAttribute("转移中")} disabled={!targetEditionId || saving} icon={MoveRight} onClick={() => void moveVolumeToTarget()} className="!rounded-xl !bg-[#ff4f26] !text-white hover:!bg-[#e84420]"><I18nText>确认转移</I18nText></Button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {canManageSystem && dangerActionOpen ? (
        <div className="fixed inset-0 z-[90] flex items-end justify-center bg-stone-950/40 p-0 backdrop-blur-sm md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={i18nAttribute("删除图书记录")}>
          <div className="w-full max-w-lg rounded-t-[26px] border border-stone-200 bg-white p-5 shadow-2xl md:rounded-[26px]">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-stone-950"><I18nText>删除图书记录</I18nText></h2>
                <p className="mt-2 text-sm leading-6 text-stone-600">{i18nAttribute('删除《{value0}》的书库记录和系统生成文件。你可以选择是否同时删除监控或上传目录中的源文件。', { value0: book.title })}</p>
              </div>
              <button type="button" onClick={() => setDangerActionOpen(false)} className="flex h-10 w-10 items-center justify-center rounded-xl text-stone-500 hover:bg-stone-100" aria-label={i18nAttribute("关闭")}><X size={18} /></button>
            </div>
            <label className={cn('mt-5 flex cursor-pointer gap-3 rounded-2xl border p-4 transition', deleteSource ? 'border-red-200 bg-red-50' : 'border-stone-200 bg-stone-50 hover:bg-stone-100')}>
              <input type="checkbox" checked={deleteSource} onChange={(event) => setDeleteSource(event.target.checked)} className="mt-0.5 h-4 w-4 accent-red-600" />
              <span>
                <span className="block text-sm font-semibold text-stone-900"><I18nText>同步删除源文件</I18nText></span>
                <span className="mt-1 block text-xs leading-5 text-stone-500"><I18nText>源文件将从监控或上传目录中永久删除；该操作无法恢复。</I18nText></span>
              </span>
            </label>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="secondary" className="!rounded-xl" onClick={() => setDangerActionOpen(false)}><I18nText>取消</I18nText></Button>
              <Button variant="danger" loading={busyAction === 'delete'} loadingText={i18nAttribute("删除中")} disabled={saving && busyAction !== 'delete'} icon={Trash2} onClick={() => void deleteRecord()} className="!rounded-xl">{deleteSource ? i18nAttribute("删除记录和源文件") : i18nAttribute("删除记录")}</Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

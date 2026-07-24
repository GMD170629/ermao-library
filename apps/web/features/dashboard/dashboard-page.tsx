'use client';

import { ArrowRight, BookOpen, Headphones, Images, Plus } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { BookshelfSection } from '../../components/book/bookshelf';
import { Cover } from '../../components/book/cover';
import { MobileNavigationTrigger } from '../../components/layout/mobile-navigation';
import { Progress } from '../../components/ui/progress';
import { useI18n } from '../../i18n/provider';
import { useAudioPlayback } from '../audio/audio-playback-provider';
import { UploadBookDialog } from '../library/upload-book-dialog';
import type { WorkView } from '../../types/work';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type ContinueItem = {
  book: WorkView;
  progress: number;
  lastReadAt: string;
  chapter: string | null;
  position: string;
} | null;

async function api<T>(path: string): Promise<T> {
  const response = await fetch(path);
  const payload = (await response.json()) as { ok: boolean; data?: T; error?: { message: string } };
  if (!payload.ok || !payload.data) throw new Error(payload.error?.message ?? '读取数据失败');
  return payload.data;
}

function shortReadTime(value: string, locale: string, t: (source: string, values?: Record<string, string>) => string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return t('上次使用到 {value0}', {
      value0: date.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })
    });
  }
  return t('上次使用于 {value0}', {
    value0: date.toLocaleDateString(locale, { month: 'numeric', day: 'numeric' })
  });
}

function recentMediaKind(book: WorkView) {
  const group = book.mediaGroups?.find((candidate) => candidate.recentEditionId === book.recentEditionId);
  if (group) return group.kind;
  if (book.mediaKind) return book.mediaKind;
  return book.type === 'audiobook' ? 'AUDIOBOOK' : book.type === 'comic' ? 'COMIC' : 'EBOOK';
}

export function DashboardPage() {
  const { t: i18nAttribute } = useAttributeI18n();
  const router = useRouter();
  const audioPlayback = useAudioPlayback();
  const { locale, t } = useI18n();
  const [continueItem, setContinueItem] = useState<ContinueItem>(null);
  const [recentReading, setRecentReading] = useState<WorkView[]>([]);
  const [recentBooks, setRecentBooks] = useState<WorkView[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.allSettled([
      api<{ item: ContinueItem }>('/api/dashboard/continue-reading'),
      api<{ books: WorkView[] }>('/api/works?visibility=active&sort=recent_read&pageSize=10'),
      api<{ books: WorkView[] }>('/api/dashboard/recent-books?limit=10')
    ]).then(([continueResult, readingResult, addedResult]) => {
      if (!active) return;
      if (continueResult.status === 'fulfilled') setContinueItem(continueResult.value.item);
      if (readingResult.status === 'fulfilled') {
        setRecentReading(readingResult.value.books.filter((book) => Boolean(book.lastReadAt)).slice(0, 10));
      }
      if (addedResult.status === 'fulfilled') setRecentBooks(addedResult.value.books.slice(0, 10));

      const failure = [continueResult, readingResult, addedResult].find((result) => result.status === 'rejected');
      setError(failure?.status === 'rejected' ? (failure.reason instanceof Error ? failure.reason.message : '部分书库内容暂时无法读取') : '');
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  const continueAuthor = continueItem?.book.author.trim() && continueItem.book.author !== '未知作者' ? continueItem.book.author : null;

  return (
    <div className="mx-auto max-w-[1280px]">
      <header className="flex items-start justify-between gap-6">
        <div className="flex min-w-0 items-center gap-3 sm:gap-4">
          <MobileNavigationTrigger />
          <h1 className="truncate text-[40px] font-semibold leading-none tracking-[-0.035em] text-[#1E1D1B] sm:text-[46px]"><I18nText>主页</I18nText></h1>
        </div>
        <button
          type="button"
          onClick={() => setUploadDialogOpen(true)}
          aria-label={i18nAttribute("上传读物")}
          title={i18nAttribute("上传读物")}
          className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#FF4F2A] text-white transition hover:bg-[#E94320] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]"
        >
          <Plus size={22} strokeWidth={1.7} />
        </button>
      </header>

      <UploadBookDialog
        open={uploadDialogOpen}
        onClose={() => setUploadDialogOpen(false)}
        onImported={() => setError('')}
        onError={setError}
      />

      {error ? <div className="mt-6 rounded-xl bg-[#FFF2EC] px-4 py-3 text-sm text-[#A9462F]">{error}</div> : null}

      <section className="mt-6">
        <h2 className="text-[22px] font-semibold tracking-tight text-[#24211F]"><I18nText>继续</I18nText></h2>
        {loading ? (
          <div className="mt-4 flex min-h-[244px] items-center rounded-2xl bg-black/[0.025] px-7 text-sm text-[#817B75]" role="status" aria-live="polite"><I18nText>正在读取最近进度...</I18nText></div>
        ) : continueItem ? (
          <div className="mt-4 flex min-h-[248px] flex-col gap-6 rounded-2xl bg-[#F4F1EE] p-4 sm:flex-row sm:items-center lg:px-6">
            <Link
              href={`/works/${continueItem.book.id}`}
              aria-label={i18nAttribute("查看《{value0}》详情", { value0: continueItem.book.title })}
              className="shrink-0 rounded-[9px] outline-none transition hover:-translate-y-0.5 focus-visible:ring-2 focus-visible:ring-[#F6B7A5]"
            >
              <Cover book={continueItem.book} size="large" priority className="h-[220px] w-[150px] rounded-[9px] shadow-[0_6px_18px_rgba(44,36,31,0.2)]" />
            </Link>
            <div className="min-w-0 flex-1 sm:pl-3">
              <h3 data-i18n-skip className="line-clamp-2 text-[27px] font-semibold tracking-[-0.025em] text-[#22201E]">
                <Link href={`/works/${continueItem.book.id}`} className="rounded-sm transition hover:text-[#EF4D2F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]">
                  {continueItem.book.title}
                </Link>
              </h3>
              {continueAuthor ? <p data-i18n-skip className="mt-1.5 text-sm text-[#746F69]">{continueAuthor}</p> : null}
              <p data-i18n-skip={continueItem.chapter ?? continueItem.book.chapter ? '' : undefined} className="mt-8 line-clamp-1 text-[15px] text-[#494540]">{continueItem.chapter ?? continueItem.book.chapter ?? i18nAttribute("继续上次阅读")}</p>
              <div className="mt-4 flex max-w-[560px] items-center gap-4">
                <Progress value={continueItem.progress} className="h-1.5 flex-1 bg-[#DDD8D3]" />
                <span className="text-sm tabular-nums text-[#706B65]">{Math.round(continueItem.progress)}%</span>
              </div>
            </div>
            <div className="flex shrink-0 flex-col items-start gap-3 sm:items-center sm:px-3">
              {(() => {
                const kind = recentMediaKind(continueItem.book);
                const audioGroup = continueItem.book.mediaGroups?.find((group) => group.kind === 'AUDIOBOOK');
                const editionId = kind === 'AUDIOBOOK'
                  ? audioGroup?.recentEditionId ?? audioGroup?.primaryEditionId ?? continueItem.book.editions.find((edition) => edition.mediaKind === 'AUDIOBOOK')?.id ?? null
                  : continueItem.book.recentEditionId ?? continueItem.book.editionId;
                const audioEdition = editionId ? continueItem.book.editions.find((edition) => edition.id === editionId) : null;
                const volumeQuery = continueItem.book.recentVolumeId ? `?volume=${encodeURIComponent(continueItem.book.recentVolumeId)}` : '';
                const href = editionId ? `/reader/${editionId}${volumeQuery}` : null;
                const label = kind === 'AUDIOBOOK' ? '继续听' : kind === 'COMIC' ? '继续看' : '继续阅读';
                const ContinueIcon = kind === 'AUDIOBOOK' ? Headphones : kind === 'COMIC' ? Images : BookOpen;
                return <button
                type="button"
                disabled={!editionId}
                onClick={() => {
                  if (!editionId) return;
                  if (kind === 'AUDIOBOOK') {
                    void audioPlayback.loadEdition(editionId, {
                      autoplay: true,
                      summary: {
                        editionId,
                        workId: continueItem.book.id,
                        title: continueItem.book.title,
                        author: continueItem.book.author === '未知作者' ? null : continueItem.book.author,
                        coverUrl: continueItem.book.coverUrl,
                        versionName: audioEdition?.versionName ?? null,
                        narrator: audioEdition?.narrator ?? null,
                        chapterTitle: continueItem.chapter
                      }
                    });
                  } else if (href) {
                    router.push(href);
                  }
                }}
                className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-[#F7D8CE] px-6 text-[15px] font-semibold text-[#EF4D2F] transition hover:bg-[#F4C8BA] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]"
              >
                <ContinueIcon size={18} strokeWidth={1.9} />
                {i18nAttribute(label)}
              </button>;
              })()}
              <span className="text-xs text-[#8A847E]">{shortReadTime(continueItem.lastReadAt, locale, t)}</span>
            </div>
          </div>
        ) : (
          <div className="mt-4 flex min-h-[180px] flex-col items-start justify-center rounded-2xl bg-[#F4F1EE] px-7">
            <div className="text-lg font-medium text-[#3A3632]"><I18nText>还没有阅读记录</I18nText></div>
            <p className="mt-2 text-sm text-[#817B75]"><I18nText>打开任意读物后，这里会接续你的阅读位置。</I18nText></p>
            <button type="button" onClick={() => router.push('/library')} className="mt-5 text-sm font-medium text-[#EF4D2F]"><I18nText>浏览全部图书</I18nText></button>
          </div>
        )}
      </section>

      <BookSection
        title={i18nAttribute("最近阅读")}
        books={recentReading}
        loading={loading}
        emptyText={i18nAttribute("最近阅读的图书会显示在这里。")}
        onMore={() => router.push('/library?sort=recent_read')}
        onOpen={(book) => router.push(`/works/${book.id}`)}
      />

      <BookSection
        title={i18nAttribute("最近加入")}
        books={recentBooks}
        loading={loading}
        emptyText={i18nAttribute("还没有加入图书，点击右上角“+”上传第一本读物。")}
        onMore={() => router.push('/library?sort=recent_import')}
        onOpen={(book) => router.push(`/works/${book.id}`)}
      />
    </div>
  );
}

function BookSection({
  title,
  books,
  loading,
  emptyText,
  onMore,
  onOpen
}: {
  title: string;
  books: WorkView[];
  loading: boolean;
  emptyText: string;
  onMore: () => void;
  onOpen: (book: WorkView) => void;
}) {
  const { t: i18nAttribute } = useAttributeI18n();
  if (!loading && books.length > 0) {
    const recentReadingTitle = i18nAttribute("最近阅读");
    return (
      <BookshelfSection
        title={title}
        books={books}
        onOpen={onOpen}
        testId={`dashboard-${title === recentReadingTitle ? 'recent-reading' : 'recent-added'}-shelf`}
        action={(
          <button type="button" onClick={onMore} className="inline-flex items-center gap-1.5 text-sm font-medium text-[#EF4D2F] transition hover:text-[#C83B23]">
            <I18nText>查看全部</I18nText><ArrowRight size={16} strokeWidth={1.8} />
          </button>
        )}
      />
    );
  }

  return (
    <section className="mt-7">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-[22px] font-semibold tracking-tight text-[#24211F]">{title}</h2>
        <button type="button" onClick={onMore} className="inline-flex items-center gap-1.5 text-sm font-medium text-[#EF4D2F] transition hover:text-[#C83B23]">
          <I18nText>查看全部</I18nText><ArrowRight size={16} strokeWidth={1.8} />
        </button>
      </div>
      {loading ? (
        <div className="mt-5 h-[220px] animate-pulse rounded-2xl bg-black/[0.025]" />
      ) : (
        <div className="mt-5 rounded-2xl bg-black/[0.025] px-6 py-8 text-sm text-[#817B75]">{emptyText}</div>
      )}
    </section>
  );
}

'use client';

import { ArrowRight, BookOpen, Headphones, Images, Plus } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { BookCard } from '../../components/book/book-card';
import { Cover } from '../../components/book/cover';
import { MobileNavigationTrigger } from '../../components/layout/mobile-navigation';
import { Progress } from '../../components/ui/progress';
import { useAudioPlayback } from '../audio/audio-playback-provider';
import type { WorkView } from '../../types/work';

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

function shortReadTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return `上次使用到 ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
  }
  return `上次使用于 ${date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })}`;
}

function recentMediaKind(book: WorkView) {
  const group = book.mediaGroups?.find((candidate) => candidate.recentEditionId === book.recentEditionId);
  if (group) return group.kind;
  if (book.mediaKind) return book.mediaKind;
  return book.type === 'audiobook' ? 'AUDIOBOOK' : book.type === 'comic' ? 'COMIC' : 'EBOOK';
}

export function DashboardPage() {
  const router = useRouter();
  const audioPlayback = useAudioPlayback();
  const [continueItem, setContinueItem] = useState<ContinueItem>(null);
  const [recentReading, setRecentReading] = useState<WorkView[]>([]);
  const [recentBooks, setRecentBooks] = useState<WorkView[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    Promise.allSettled([
      api<{ item: ContinueItem }>('/api/dashboard/continue-reading'),
      api<{ books: WorkView[] }>('/api/works?visibility=active&sort=recent_read&pageSize=5'),
      api<{ books: WorkView[] }>('/api/dashboard/recent-books?limit=5')
    ]).then(([continueResult, readingResult, addedResult]) => {
      if (!active) return;
      if (continueResult.status === 'fulfilled') setContinueItem(continueResult.value.item);
      if (readingResult.status === 'fulfilled') {
        setRecentReading(readingResult.value.books.filter((book) => Boolean(book.lastReadAt)).slice(0, 5));
      }
      if (addedResult.status === 'fulfilled') setRecentBooks(addedResult.value.books.slice(0, 5));

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
          <h1 className="truncate text-[40px] font-semibold leading-none tracking-[-0.035em] text-[#1E1D1B] sm:text-[46px]">主页</h1>
        </div>
        <button
          type="button"
          onClick={() => router.push('/library?upload=1')}
          aria-label="上传读物"
          title="上传读物"
          className="flex h-12 w-12 items-center justify-center rounded-full border border-black/[0.12] bg-white/55 text-[#252321] transition hover:border-[#EF4D2F]/40 hover:bg-[#FFF4EF] hover:text-[#EF4D2F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]"
        >
          <Plus size={25} strokeWidth={1.6} />
        </button>
      </header>

      {error ? <div className="mt-6 rounded-xl bg-[#FFF2EC] px-4 py-3 text-sm text-[#A9462F]">{error}</div> : null}

      <section className="mt-6">
        <h2 className="text-[22px] font-semibold tracking-tight text-[#24211F]">继续</h2>
        {loading ? (
          <div className="mt-4 flex min-h-[244px] items-center rounded-2xl bg-black/[0.025] px-7 text-sm text-[#817B75]" role="status" aria-live="polite">正在读取最近进度...</div>
        ) : continueItem ? (
          <div className="mt-4 flex min-h-[248px] flex-col gap-6 rounded-2xl bg-[#F4F1EE] p-4 sm:flex-row sm:items-center lg:px-6">
            <Link
              href={`/works/${continueItem.book.id}`}
              aria-label={`查看《${continueItem.book.title}》详情`}
              className="shrink-0 rounded-[9px] outline-none transition hover:-translate-y-0.5 focus-visible:ring-2 focus-visible:ring-[#F6B7A5]"
            >
              <Cover book={continueItem.book} size="large" priority className="h-[220px] w-[150px] rounded-[9px] shadow-[0_6px_18px_rgba(44,36,31,0.2)]" />
            </Link>
            <div className="min-w-0 flex-1 sm:pl-3">
              <h3 className="line-clamp-2 text-[27px] font-semibold tracking-[-0.025em] text-[#22201E]">
                <Link href={`/works/${continueItem.book.id}`} className="rounded-sm transition hover:text-[#EF4D2F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]">
                  {continueItem.book.title}
                </Link>
              </h3>
              {continueAuthor ? <p className="mt-1.5 text-sm text-[#746F69]">{continueAuthor}</p> : null}
              <p className="mt-8 line-clamp-1 text-[15px] text-[#494540]">{continueItem.chapter ?? continueItem.book.chapter ?? '继续上次阅读'}</p>
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
                {label}
              </button>;
              })()}
              <span className="text-xs text-[#8A847E]">{shortReadTime(continueItem.lastReadAt)}</span>
            </div>
          </div>
        ) : (
          <div className="mt-4 flex min-h-[180px] flex-col items-start justify-center rounded-2xl bg-[#F4F1EE] px-7">
            <div className="text-lg font-medium text-[#3A3632]">还没有阅读记录</div>
            <p className="mt-2 text-sm text-[#817B75]">打开任意读物后，这里会接续你的阅读位置。</p>
            <button type="button" onClick={() => router.push('/library')} className="mt-5 text-sm font-medium text-[#EF4D2F]">浏览全部图书</button>
          </div>
        )}
      </section>

      <BookSection
        title="最近阅读"
        books={recentReading}
        loading={loading}
        emptyText="最近阅读的图书会显示在这里。"
        onMore={() => router.push('/library?sort=recent_read')}
        onOpen={(book) => router.push(`/works/${book.id}`)}
      />

      <BookSection
        title="最近加入"
        books={recentBooks}
        loading={loading}
        emptyText="还没有加入图书，点击右上角“+”上传第一本读物。"
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
  return (
    <section className="mt-6">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-[22px] font-semibold tracking-tight text-[#24211F]">{title}</h2>
        <button type="button" onClick={onMore} className="inline-flex items-center gap-1.5 text-sm font-medium text-[#EF4D2F] transition hover:text-[#C83B23]">
          查看全部
          <ArrowRight size={16} strokeWidth={1.8} />
        </button>
      </div>
      {loading ? (
        <div className="mt-5 h-[360px] animate-pulse rounded-2xl bg-black/[0.025]" />
      ) : books.length > 0 ? (
        <div
          data-testid={`dashboard-${title === '最近阅读' ? 'recent-reading' : 'recent-added'}-rail`}
          role="region"
          aria-label={`${title}图书横向列表`}
          tabIndex={0}
          className="mt-4 grid snap-x snap-proximity grid-flow-col gap-7 overflow-x-auto overscroll-x-contain pb-3"
          style={{ gridAutoColumns: 'max(152px, calc((100% - 7rem) / 5))' }}
        >
          {books.map((book) => (
            <div key={book.id} className="min-w-0 snap-start">
              <BookCard book={book} onClick={() => onOpen(book)} />
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-5 rounded-2xl bg-black/[0.025] px-6 py-8 text-sm text-[#817B75]">{emptyText}</div>
      )}
    </section>
  );
}

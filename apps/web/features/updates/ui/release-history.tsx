'use client';

import { ChevronDown } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useI18n } from '@/i18n/provider';
import { fetchReleaseNote } from '../api/client';
import { useReleaseFeed } from '../application/release-feed-context';
import { extractLocalizedReleaseNote } from '../model/release-notes';
import type { ReleaseSummary } from '../model/types';
import { UpdateOperations } from './update-operations';
import { ReleaseMarkdown } from './release-markdown';

function ReleaseEntry({ release, initiallyOpen }: { release: ReleaseSummary; initiallyOpen: boolean }) {
  const { locale, formatDate, t } = useI18n();
  const { runtime } = useReleaseFeed();
  const [open, setOpen] = useState(initiallyOpen);
  const [note, setNote] = useState<{ locale: string; markdown: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || note?.locale === locale) return undefined;
    const controller = new AbortController();
    setError(null);
    fetchReleaseNote(release.notesPath, controller.signal)
      .then((markdown) => setNote({ locale, markdown: extractLocalizedReleaseNote(markdown, locale) }))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '暂时无法读取更新说明');
      });
    return () => controller.abort();
  }, [locale, note?.locale, open, release.notesPath]);

  return (
    <article className="overflow-hidden rounded-2xl border border-[#DEDAD4] bg-white">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-16 w-full items-center gap-3 px-5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#F6B7A5]"
      >
        <span className="font-mono text-base font-semibold text-[#2A2825]">v{release.version}</span>
        {release.version === runtime?.current_version ? <span className="rounded-full bg-[#F9DED4] px-2 py-0.5 text-xs font-medium text-[#D94327]">{t('当前版本')}</span> : null}
        <time className="ml-auto text-xs text-[#827B73]" dateTime={release.publishedAt}>{formatDate(release.publishedAt)}</time>
        <ChevronDown size={17} className={`text-[#827B73] transition ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>
      {open ? (
        <div className="border-t border-[#E5E1DC] px-5 py-5">
          {note?.locale === locale ? <ReleaseMarkdown markdown={note.markdown} /> : null}
          {note?.locale !== locale && !error ? <p className="text-sm text-[#827B73]">{t('正在读取更新说明…')}</p> : null}
          {error ? <p className="text-sm text-[#A33B28]">{t(error)}</p> : null}
          <a href={release.releaseUrl} target="_blank" rel="noreferrer" className="mt-4 inline-block text-xs font-medium text-[#D94327] underline">
            {t('在 GitHub 查看此版本')}
          </a>
        </div>
      ) : null}
    </article>
  );
}

export function ReleaseHistory() {
  const { state } = useReleaseFeed();
  const { t } = useI18n();
  return (
    <section className="mt-8 border-t border-[#DEDAD4] pt-7" aria-labelledby="release-history-title">
      <h3 id="release-history-title" className="text-lg font-semibold text-[#2A2825]">{t('更新与版本历史')}</h3>
      <p className="mt-2 text-sm leading-6 text-[#716B64]">{t('更新说明与 GitHub Release 保持一致。')}</p>
      <UpdateOperations />
      {state.status === 'ready' ? (
        <div className="mt-5 space-y-3">
          {state.feed.releases.map((release, index) => (
            <ReleaseEntry key={release.version} release={release} initiallyOpen={index === 0} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function RuntimeVersion() {
  const { runtime } = useReleaseFeed();
  return <>{runtime ? `v${runtime.current_version}` : '—'}</>;
}

'use client';

import { AlertCircle, CheckCircle2, ChevronDown, FlaskConical, RefreshCw, Sparkles } from 'lucide-react';
import rootPackage from '../../../../../package.json';
import { useEffect, useState } from 'react';
import { useI18n } from '@/i18n/provider';
import { fetchReleaseNote } from '../api/client';
import { useReleaseFeed } from '../application/release-feed-context';
import { extractLocalizedReleaseNote, updateStatus } from '../model/release-notes';
import type { ReleaseSummary } from '../model/types';
import { ReleaseMarkdown } from './release-markdown';

function StatusCard() {
  const { state, retry } = useReleaseFeed();
  const { formatDateTime, t } = useI18n();
  if (state.status === 'loading') {
    return <div className="rounded-2xl border border-[#DEDAD4] bg-[#F7F5F2] p-5 text-sm text-[#716B64]">{t('正在检查更新…')}</div>;
  }
  if (state.status === 'error') {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-[#E8C8C1] bg-[#FFF4F1] p-5 text-sm text-[#8D3828]">
        <AlertCircle size={19} aria-hidden="true" />
        <span className="min-w-0 flex-1">{t(state.message)}</span>
        <button type="button" onClick={retry} className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-[#DFAE9F] px-3 font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]">
          <RefreshCw size={16} aria-hidden="true" />
          {t('重试')}
        </button>
      </div>
    );
  }
  const status = updateStatus(rootPackage.version, state.feed);
  if (status.kind === 'update-available') {
    return (
      <div className="rounded-2xl border border-[#F1B8A8] bg-[#FFF2ED] p-5">
        <div className="flex items-start gap-3">
          <Sparkles size={20} className="mt-0.5 text-[#ED4D2D]" aria-hidden="true" />
          <div>
            <h3 className="font-semibold text-[#8F2F1D]">{t('发现新版本 v{version}', { version: status.latest.version })}</h3>
            <p className="mt-1 text-sm leading-6 text-[#7B5148]">
              {t('当前版本 v{current}，最新版本发布于 {date}。', {
                current: rootPackage.version,
                date: formatDateTime(status.latest.publishedAt)
              })}
            </p>
          </div>
        </div>
      </div>
    );
  }
  if (status.kind === 'development') {
    return (
      <div className="flex items-center gap-3 rounded-2xl border border-[#D7D3E7] bg-[#F5F3FA] p-5 text-sm text-[#5F577C]">
        <FlaskConical size={19} aria-hidden="true" />
        <span>{t('当前运行的是高于最新正式版的开发版本。')}</span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-[#CFE0CF] bg-[#F2F8F1] p-5 text-sm text-[#426443]">
      <CheckCircle2 size={19} aria-hidden="true" />
      <span>{t('当前已是最新正式版本。')}</span>
    </div>
  );
}

function ReleaseEntry({ release, initiallyOpen }: { release: ReleaseSummary; initiallyOpen: boolean }) {
  const { locale, formatDate, t } = useI18n();
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
        {release.version === rootPackage.version ? <span className="rounded-full bg-[#F9DED4] px-2 py-0.5 text-xs font-medium text-[#D94327]">{t('当前版本')}</span> : null}
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
      <div className="mt-4"><StatusCard /></div>
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

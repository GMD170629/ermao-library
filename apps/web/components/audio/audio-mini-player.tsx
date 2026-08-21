'use client';

import {
  ArrowLeft,
  Check,
  Clock3,
  Headphones,
  ListMusic,
  LoaderCircle,
  Pause,
  Play,
  RotateCcw,
  Settings2,
  SkipBack,
  SkipForward,
  Volume1,
  Volume2,
  X
} from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { formatAudioTime } from '../../features/audio/audio-model';
import { useAudioPlayback } from '../../features/audio/audio-playback-provider';
import { AUDIO_PLAYBACK_RATE_OPTIONS } from '../../lib/audio-device-preferences';
import { withBasePath } from '../../lib/base-path';
import { cn } from '../ui/cn';
import { ResourceSelect } from '../ui/resource-select';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

const hiddenPrefixes = ['/login', '/setup', '/forgot-password', '/reset-password', '/offline'];
const sleepOptions = [15, 30, 45, 60] as const;
const chaptersPanelId = 'audio-mini-player-chapters';
const settingsPanelId = 'audio-mini-player-settings';

type MiniPlayerPanel = 'chapters' | 'settings' | null;

export function AudioMiniPlayer() {
  const { t: i18nAttribute } = useAttributeI18n();
  const pathname = usePathname();
  const player = useAudioPlayback();
  const bootstrap = player.bootstrap;
  const pendingSummary = player.pendingResourceId && player.pendingSummary
    && player.pendingResourceId === player.pendingSummary.resourceId
    ? player.pendingSummary
    : null;
  const [openPanel, setOpenPanel] = useState<MiniPlayerPanel>(null);
  const [clock, setClock] = useState(() => Date.now());
  const rootRef = useRef<HTMLElement>(null);
  const chaptersButtonRef = useRef<HTMLButtonElement>(null);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const visible = Boolean(bootstrap || pendingSummary) && !hiddenPrefixes.some((prefix) => pathname === prefix || pathname.startsWith(prefix));

  useEffect(() => {
    if (!visible) {
      delete document.documentElement.dataset.audioMiniPlayer;
      return undefined;
    }
    document.documentElement.dataset.audioMiniPlayer = pathname.startsWith('/reader/') ? 'reader' : 'visible';
    return () => { delete document.documentElement.dataset.audioMiniPlayer; };
  }, [pathname, visible]);

  useEffect(() => {
    setOpenPanel(null);
  }, [bootstrap?.resource.id, pathname]);

  useEffect(() => {
    if (!openPanel) return undefined;
    const closeFromOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpenPanel(null);
    };
    const closeFromKeyboard = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      const trigger = openPanel === 'chapters' ? chaptersButtonRef.current : settingsButtonRef.current;
      setOpenPanel(null);
      window.requestAnimationFrame(() => trigger?.focus());
    };
    document.addEventListener('pointerdown', closeFromOutside);
    document.addEventListener('keydown', closeFromKeyboard);
    return () => {
      document.removeEventListener('pointerdown', closeFromOutside);
      document.removeEventListener('keydown', closeFromKeyboard);
    };
  }, [openPanel]);

  useEffect(() => {
    if (player.sleepTimerMode !== 'timer' || !player.sleepTimerEndsAt) return undefined;
    setClock(Date.now());
    const timer = window.setInterval(() => setClock(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, [player.sleepTimerEndsAt, player.sleepTimerMode]);

  const chapterItems = !bootstrap
    ? []
    : bootstrap.chapters.length > 0
      ? bootstrap.chapters.map((chapter) => ({
          id: chapter.id,
          title: chapter.title,
          durationMs: Math.max(0, chapter.endMs - chapter.startMs),
          active: chapter.id === player.chapter?.id,
          play: () => player.selectChapter(chapter.id, true)
        }))
      : bootstrap.tracks.map((track, index) => ({
          id: track.assetId,
          title: track.title,
          durationMs: track.durationMs,
          active: index === player.trackIndex,
          play: () => player.selectTrack(index, true)
        }));

  if (!visible) return null;

  if (pendingSummary) {
    const pendingCoverUrl = pendingSummary.coverUrl
      ? withBasePath(pendingSummary.coverUrl)
      : withBasePath(`/api/books/${encodeURIComponent(pendingSummary.bookId)}/cover?size=small`);
    const pendingHref = `/books/${encodeURIComponent(pendingSummary.bookId)}?resourceId=${encodeURIComponent(pendingSummary.resourceId)}`;
    return (
      <section
        ref={rootRef}
        className="shuku-audio-mini-player fixed z-[60]"
        data-reader-overlay={pathname.startsWith('/reader/') ? 'true' : undefined}
        aria-label={i18nAttribute("有声书迷你播放器")}
        data-testid="audio-mini-player"
      >
        <div className="overflow-hidden rounded-[20px] border border-black/[0.08] bg-[#FFFEFC]/95 shadow-[0_14px_45px_rgba(54,43,35,0.18)] backdrop-blur-xl">
          <div className="flex min-h-[84px] items-center gap-3 px-3 py-2.5 sm:px-4">
            <Link href={pendingHref} className="flex min-w-0 flex-1 items-center gap-3 rounded-xl text-left hover:bg-black/[0.035]" aria-label={i18nAttribute("打开《{value0}》图书详情", { value0: pendingSummary.title })}>
              <span className="relative h-12 w-12 shrink-0 overflow-hidden rounded-[9px] bg-[#EEE8E1] shadow-sm">
                <Image src={pendingCoverUrl} alt="" fill sizes="48px" unoptimized className="object-cover" />
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold text-[#292724]">{pendingSummary.title}</span>
                <span className={cn('mt-0.5 block truncate text-xs', player.loadError ? 'text-[#C84A32]' : 'text-[#77716B]')} role="status" aria-live="polite">
                  {player.loadError ? i18nAttribute("加载失败：{value0}", { value0: player.loadError }) : pendingSummary.chapterTitle ? i18nAttribute("正在准备：{value0}", { value0: pendingSummary.chapterTitle }) : i18nAttribute("正在准备有声书…")}
                </span>
              </span>
            </Link>
            {player.loadError ? (
              <button type="button" onClick={() => void player.retry()} className="flex min-h-11 items-center gap-1.5 rounded-xl bg-[#FFF0EA] px-3 text-sm font-semibold text-[#C84A32] hover:bg-[#FFE6DC]" aria-label={i18nAttribute("重试播放")}>
                <RotateCcw size={17} /> <span className="hidden sm:inline"><I18nText>重试</I18nText></span>
              </button>
            ) : <LoaderCircle size={22} className="shrink-0 animate-spin text-[#EF4D2F] motion-reduce:animate-none" aria-hidden="true" />}
            {bootstrap ? (
              <button type="button" onClick={player.cancelResourceSwitch} className="flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-xl px-2 text-sm font-semibold text-[#625C56] hover:bg-black/[0.05]" aria-label={i18nAttribute("返回原播放")}>
                <ArrowLeft size={17} aria-hidden="true" /> <span className="hidden xl:inline"><I18nText>原播放</I18nText></span>
              </button>
            ) : null}
            <button type="button" onClick={player.close} className="flex min-h-11 min-w-11 items-center justify-center rounded-xl text-[#8A847E] hover:bg-black/[0.05] hover:text-[#3C3935]" aria-label={i18nAttribute("关闭播放器")}>
              <X size={17} />
            </button>
          </div>
        </div>
      </section>
    );
  }

  if (!bootstrap) return null;

  const coverUrl = bootstrap.book.coverUrl
    ? withBasePath(bootstrap.book.coverUrl)
    : withBasePath(`/api/books/${encodeURIComponent(bootstrap.book.id)}/cover?size=small`);
  const bookHref = `/books/${encodeURIComponent(bootstrap.book.id)}?resourceId=${encodeURIComponent(bootstrap.resource.id)}`;
  const isPlaying = player.lifecycle === 'playing';
  const isLoading = player.lifecycle === 'loading';
  const playbackError = player.loadError ?? player.error;
  const progressMaximum = Math.max(player.totalDurationMs, 1);
  const elapsedLabel = formatAudioTime(player.absolutePositionMs, true);
  const durationLabel = formatAudioTime(player.totalDurationMs, true);
  const sleepRemainingMinutes = player.sleepTimerEndsAt
    ? Math.max(0, Math.ceil((player.sleepTimerEndsAt - clock) / 60_000))
    : null;
  const sleepStatus = player.sleepTimerMode === 'chapter'
    ? '本章结束后停止'
    : player.sleepTimerMode === 'timer' && sleepRemainingMinutes !== null
      ? `剩余 ${sleepRemainingMinutes} 分钟`
      : '未开启';

  const togglePanel = (panel: Exclude<MiniPlayerPanel, null>) => {
    setOpenPanel((current) => current === panel ? null : panel);
  };

  return (
    <section
      ref={rootRef}
      className="shuku-audio-mini-player fixed z-[60]"
      data-reader-overlay={pathname.startsWith('/reader/') ? 'true' : undefined}
      aria-label={i18nAttribute("有声书迷你播放器")}
      data-testid="audio-mini-player"
    >
      {openPanel === 'chapters' ? (
        <section
          id={chaptersPanelId}
          className="shuku-audio-mini-panel flex flex-col overflow-hidden rounded-[20px] border border-black/[0.08] bg-[#FFFEFC]/[0.98] shadow-[0_18px_55px_rgba(54,43,35,0.20)] backdrop-blur-xl"
          role="region"
          aria-label={bootstrap.chapters.length > 0 ? i18nAttribute("章节列表") : i18nAttribute("音轨列表")}
        >
          <header className="flex items-end justify-between gap-4 border-b border-black/[0.07] px-4 py-3.5">
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-[#292724]">{bootstrap.chapters.length > 0 ? i18nAttribute("章节") : i18nAttribute("音轨")}</h2>
              <p className="mt-0.5 text-xs text-[#817B74]"><I18nText>共 </I18nText>{chapterItems.length} {bootstrap.chapters.length > 0 ? i18nAttribute("章") : i18nAttribute("轨")} · {durationLabel}</p>
            </div>
            <button type="button" onClick={() => setOpenPanel(null)} className="flex min-h-11 min-w-11 items-center justify-center rounded-full text-[#77716B] hover:bg-black/[0.05]" aria-label={i18nAttribute("关闭章节列表")}>
              <X size={17} />
            </button>
          </header>
          {bootstrap.availableResources.length > 1 ? (
            <div className="border-b border-black/[0.07] px-4 py-2.5">
              <ResourceSelect
                items={bootstrap.availableResources.map((resource) => ({ id: resource.id, title: resource.title }))}
                value={bootstrap.resource.id}
                onChange={(resourceId) => void player.loadResource(resourceId)}
                disabled={Boolean(player.pendingResourceId)}
                compact
                className="w-full"
              />
            </div>
          ) : null}
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2">
            {chapterItems.map((item, index) => (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  item.play();
                  setOpenPanel(null);
                }}
                className={cn('flex min-h-[56px] w-full items-center gap-3 rounded-xl px-2.5 text-left hover:bg-black/[0.04]', item.active && 'bg-[#FCE9E2] hover:bg-[#FCE9E2]')}
                aria-current={item.active ? 'true' : undefined}
              >
                <span className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs tabular-nums', item.active ? 'bg-[#EF4D2F] text-white' : 'bg-black/[0.045] text-[#756F69]')}>
                  {item.active && isPlaying ? <Headphones size={14} aria-hidden="true" /> : item.active ? <Check size={14} aria-hidden="true" /> : index + 1}
                </span>
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-[#38342F]">{item.title}</span>
                <span className="shrink-0 text-xs tabular-nums text-[#8A847E]">{formatAudioTime(item.durationMs, true)}</span>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {openPanel === 'settings' ? (
        <section
          id={settingsPanelId}
          className="shuku-audio-mini-panel overflow-y-auto overscroll-contain rounded-[20px] border border-black/[0.08] bg-[#FFFEFC]/[0.98] p-4 shadow-[0_18px_55px_rgba(54,43,35,0.20)] backdrop-blur-xl"
          role="region"
          aria-label={i18nAttribute("播放设置")}
        >
          <header className="flex items-center justify-between gap-4">
            <h2 className="text-sm font-semibold text-[#292724]"><I18nText>播放设置</I18nText></h2>
            <button type="button" onClick={() => setOpenPanel(null)} className="flex min-h-11 min-w-11 items-center justify-center rounded-full text-[#77716B] hover:bg-black/[0.05]" aria-label={i18nAttribute("关闭播放设置")}>
              <X size={17} />
            </button>
          </header>

          <div className="mt-3">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="font-medium text-[#4C4843]"><I18nText>播放速度</I18nText></span>
              <span className="font-semibold tabular-nums text-[#C8452B]">{player.playbackRate}×</span>
            </div>
            <div className="mt-2 grid grid-cols-4 gap-1.5" role="group" aria-label={i18nAttribute("选择播放速度")}>
              {AUDIO_PLAYBACK_RATE_OPTIONS.map((rate) => (
                <button
                  key={rate}
                  type="button"
                  onClick={() => player.setPlaybackRate(rate)}
                  className={cn('min-h-11 rounded-xl border px-2 text-xs font-semibold tabular-nums', player.playbackRate === rate ? 'border-[#EF4D2F] bg-[#FFF0EA] text-[#C8452B]' : 'border-black/[0.07] bg-white text-[#625C56] hover:bg-black/[0.035]')}
                  aria-pressed={player.playbackRate === rate}
                >
                  {rate}×
                </button>
              ))}
            </div>
          </div>

          <div className="mt-5 border-t border-black/[0.07] pt-4">
            <label className="flex items-center gap-3 text-sm font-medium text-[#4C4843]">
              {player.volume === 0 ? <Volume1 size={18} aria-hidden="true" /> : <Volume2 size={18} aria-hidden="true" />}
              <span><I18nText>音量</I18nText></span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={player.volume}
                onChange={(event) => player.setVolume(Number(event.target.value))}
                className="h-11 min-w-0 flex-1 cursor-pointer accent-[#EF4D2F]"
                aria-label={i18nAttribute("音量")}
              />
              <span className="w-10 text-right text-xs tabular-nums text-[#817B74]">{Math.round(player.volume * 100)}%</span>
            </label>
          </div>

          <div className="mt-3 border-t border-black/[0.07] pt-4">
            <div className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-sm font-medium text-[#4C4843]"><Clock3 size={17} aria-hidden="true" /><I18nText>睡眠定时</I18nText></span>
              <span className="text-xs tabular-nums text-[#817B74]" role="status">{sleepStatus}</span>
            </div>
            <div className="mt-2 grid grid-cols-3 gap-1.5" role="group" aria-label={i18nAttribute("设置睡眠定时")}>
              <button
                type="button"
                onClick={() => player.setSleepTimer(null)}
                className={cn('min-h-11 rounded-xl border px-2 text-xs font-semibold', player.sleepTimerMode === null ? 'border-[#EF4D2F] bg-[#FFF0EA] text-[#C8452B]' : 'border-black/[0.07] bg-white text-[#625C56] hover:bg-black/[0.035]')}
                aria-pressed={player.sleepTimerMode === null}
              >
                <I18nText>关闭</I18nText></button>
              {sleepOptions.map((minutes) => (
                <button key={minutes} type="button" onClick={() => player.setSleepTimer(minutes)} className="min-h-11 rounded-xl border border-black/[0.07] bg-white px-2 text-xs font-semibold tabular-nums text-[#625C56] hover:bg-black/[0.035]">
                  {minutes} <I18nText>分钟</I18nText></button>
              ))}
              <button
                type="button"
                onClick={() => player.setSleepTimer('chapter')}
                className={cn('min-h-11 rounded-xl border px-2 text-xs font-semibold', player.sleepTimerMode === 'chapter' ? 'border-[#EF4D2F] bg-[#FFF0EA] text-[#C8452B]' : 'border-black/[0.07] bg-white text-[#625C56] hover:bg-black/[0.035]')}
                aria-pressed={player.sleepTimerMode === 'chapter'}
              >
                <I18nText>本章结束</I18nText></button>
            </div>
          </div>
        </section>
      ) : null}

      <div className="overflow-hidden rounded-[22px] border border-black/[0.07] bg-[#FFFEFC]/95 shadow-[0_16px_50px_rgba(65,48,38,0.17),inset_0_1px_0_rgba(255,255,255,0.85)] backdrop-blur-xl">
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 gap-y-1.5 px-2.5 pt-2.5 sm:px-3 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:gap-x-4 md:pt-3 lg:px-4">
          <Link href={bookHref} className="flex min-h-14 min-w-0 items-center gap-2.5 rounded-[14px] p-1 text-left transition-colors duration-200 hover:bg-black/[0.035] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4D2F]/60" aria-label={i18nAttribute("打开《{value0}》图书详情", { value0: bootstrap.book.title })}>
            <span className="relative h-12 w-12 shrink-0 overflow-hidden rounded-[10px] bg-[#EEE8E1] shadow-[0_3px_10px_rgba(62,49,40,0.16)] sm:h-[52px] sm:w-[52px]">
              <Image src={coverUrl} alt={i18nAttribute("《{value0}》封面", { value0: bootstrap.book.title })} fill sizes="52px" unoptimized className="object-cover" />
            </span>
            <span className="min-w-0 pr-1">
              <span data-i18n-skip className="block truncate text-sm font-semibold tracking-[-0.01em] text-[#292724]">{bootstrap.book.title}</span>
              <span
                className={cn('mt-1 block truncate text-xs', playbackError ? 'text-[#C84A32]' : 'text-[#77716B]')}
                title={playbackError ?? player.chapter?.title ?? player.track?.title ?? undefined}
                role={playbackError ? 'status' : undefined}
                aria-live={playbackError ? 'polite' : undefined}
              >
                {playbackError ? i18nAttribute("播放失败：{value0}", { value0: playbackError }) : player.chapter?.title ?? player.track?.title ?? i18nAttribute("准备播放")}
              </span>
            </span>
          </Link>

          <div className="flex shrink-0 items-center justify-end gap-0.5 md:order-3 md:justify-self-end md:border-l md:border-black/[0.07] md:pl-2">
            <button
              ref={chaptersButtonRef}
              type="button"
              onClick={() => togglePanel('chapters')}
              className={cn('flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-xl px-2 text-[#5F5953] transition duration-200 hover:bg-black/[0.05] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4D2F]/50', openPanel === 'chapters' && 'bg-[#FCE9E2] text-[#C8452B]')}
              aria-label={bootstrap.chapters.length > 0 ? i18nAttribute("打开章节列表") : i18nAttribute("打开音轨列表")}
              aria-expanded={openPanel === 'chapters'}
              aria-controls={chaptersPanelId}
            >
              <ListMusic size={18} aria-hidden="true" />
              <span className="hidden text-xs font-medium xl:inline">{bootstrap.chapters.length > 0 ? i18nAttribute("章节") : i18nAttribute("音轨")}</span>
            </button>
            <button
              ref={settingsButtonRef}
              type="button"
              onClick={() => togglePanel('settings')}
              className={cn('relative flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-xl px-2 text-[#5F5953] transition duration-200 hover:bg-black/[0.05] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4D2F]/50', openPanel === 'settings' && 'bg-[#FCE9E2] text-[#C8452B]')}
              aria-label={i18nAttribute("打开播放设置")}
              aria-expanded={openPanel === 'settings'}
              aria-controls={settingsPanelId}
            >
              <Settings2 size={18} aria-hidden="true" />
              <span className="hidden text-xs font-medium xl:inline"><I18nText>设置</I18nText></span>
              {player.sleepTimerMode ? <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-[#EF4D2F]" aria-hidden="true" /> : null}
            </button>
            <button type="button" onClick={player.close} className="flex min-h-11 min-w-11 items-center justify-center rounded-xl text-[#8A847E] transition duration-200 hover:bg-black/[0.05] hover:text-[#3C3935] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4D2F]/50" aria-label={i18nAttribute("关闭播放器")}>
              <X size={17} />
            </button>
          </div>

          <div className="col-span-2 flex min-w-0 items-center justify-center gap-0.5 sm:gap-1.5 md:order-2 md:col-span-1 md:justify-self-center" data-mini-player-zone="playback">
            <button type="button" onClick={player.previousChapter} className="flex min-h-11 min-w-11 items-center justify-center rounded-full text-[#57524D] transition duration-200 hover:bg-black/[0.05] active:scale-[0.94] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4D2F]/50" aria-label={i18nAttribute("上一章")}>
              <SkipBack size={18} fill="currentColor" />
            </button>
            <button type="button" onClick={() => player.seekBy(-player.skipBackwardSeconds)} className="flex min-h-11 min-w-11 items-center justify-center rounded-full text-xs font-semibold tabular-nums text-[#57524D] transition duration-200 hover:bg-black/[0.05] active:scale-[0.94] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4D2F]/50" aria-label={i18nAttribute("后退 {value0} 秒", { value0: player.skipBackwardSeconds })}>
              −{player.skipBackwardSeconds}
            </button>
            <button
              type="button"
              onClick={() => void (playbackError ? player.retry() : player.toggle())}
              className={cn('flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-full bg-[#EF4D2F] text-white shadow-[0_6px_16px_rgba(239,77,47,0.28)] transition duration-200 hover:-translate-y-0.5 hover:bg-[#DB4328] hover:shadow-[0_8px_20px_rgba(219,67,40,0.32)] active:translate-y-0 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#EF4D2F]/25', isLoading && 'cursor-wait')}
              aria-label={playbackError ? i18nAttribute("重试播放") : isPlaying ? i18nAttribute("暂停") : i18nAttribute("播放")}
              disabled={isLoading && !playbackError}
              data-testid="audio-play-toggle"
            >
              {playbackError ? <RotateCcw size={19} /> : isLoading ? <LoaderCircle size={20} className="animate-spin motion-reduce:animate-none" /> : isPlaying ? <Pause size={19} fill="currentColor" /> : <Play size={19} className="ml-0.5" fill="currentColor" />}
            </button>
            <button type="button" onClick={() => player.seekBy(player.skipForwardSeconds)} className="flex min-h-11 min-w-11 items-center justify-center rounded-full text-xs font-semibold tabular-nums text-[#57524D] transition duration-200 hover:bg-black/[0.05] active:scale-[0.94] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4D2F]/50" aria-label={i18nAttribute("前进 {value0} 秒", { value0: player.skipForwardSeconds })}>
              +{player.skipForwardSeconds}
            </button>
            <button type="button" onClick={player.nextChapter} className="flex min-h-11 min-w-11 items-center justify-center rounded-full text-[#57524D] transition duration-200 hover:bg-black/[0.05] active:scale-[0.94] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4D2F]/50" aria-label={i18nAttribute("下一章")}>
              <SkipForward size={18} fill="currentColor" />
            </button>
          </div>
        </div>

        <div className="flex min-h-10 min-w-0 items-center gap-2 px-3 pb-2 lg:px-4">
          <span className="w-11 shrink-0 text-right text-[11px] tabular-nums text-[#817B74]">{elapsedLabel}</span>
          <input
            type="range"
            min={0}
            max={progressMaximum}
            step={1000}
            value={Math.min(player.absolutePositionMs, progressMaximum)}
            onChange={(event) => player.seekToAbsolute(Number(event.target.value))}
            className="h-11 min-w-0 flex-1 cursor-pointer accent-[#EF4D2F]"
            aria-label={i18nAttribute("有声书播放进度")}
          />
          <span className="w-11 shrink-0 text-[11px] tabular-nums text-[#817B74]">{durationLabel}</span>
        </div>

        {playbackError ? (
          <div className="flex min-h-11 items-center gap-2 border-t border-[#F1D6CD] bg-[#FFF4EF] px-3 text-xs text-[#A43B26]" role="status">
            <span className="min-w-0 flex-1 truncate" title={playbackError}>{playbackError}</span>
            <button type="button" onClick={() => void player.retry()} className="min-h-11 shrink-0 rounded-lg px-2 font-semibold hover:bg-[#FFE6DC]"><I18nText>重试</I18nText></button>
          </div>
        ) : null}
      </div>
    </section>
  );
}

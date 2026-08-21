'use client';

import { AlertTriangle, LoaderCircle, RotateCcw } from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useRef } from 'react';
import { useAudioPlayback } from './audio-playback-provider';
import { I18nText } from '@/i18n/provider';

export function AudioListenRedirect({ resourceId }: { resourceId: string }) {
  const player = useAudioPlayback();
  const loadResource = player.loadResource;
  const playerBootstrap = player.bootstrap;
  const selectTrack = player.selectTrack;
  const router = useRouter();
  const searchParams = useSearchParams();
  const chapterId = searchParams.get('chapter')?.trim() || null;
  const trackParam = searchParams.get('track');
  const appliedTrackRef = useRef('');

  useEffect(() => {
    void loadResource(resourceId, {
      autoplay: false,
      chapterId: chapterId ?? undefined
    });
  }, [chapterId, loadResource, resourceId]);

  useEffect(() => {
    const bootstrap = playerBootstrap?.resource.id === resourceId ? playerBootstrap : null;
    if (!bootstrap) return;
    const targetKey = `${resourceId}:${trackParam ?? ''}`;
    if (!chapterId && trackParam !== null && appliedTrackRef.current !== targetKey) {
      const trackIndex = Number(trackParam);
      if (Number.isInteger(trackIndex) && trackIndex >= 0 && trackIndex < bootstrap.tracks.length) {
        selectTrack(trackIndex, false);
      }
      appliedTrackRef.current = targetKey;
    }
    router.replace(`/books/${encodeURIComponent(bootstrap.book.id)}?resourceId=${encodeURIComponent(bootstrap.resource.id)}`);
  }, [chapterId, playerBootstrap, router, selectTrack, trackParam, resourceId]);

  const failed = player.pendingResourceId === resourceId && Boolean(player.loadError);
  if (failed) {
    return (
      <div className="flex min-h-[60dvh] items-center justify-center px-4">
        <div className="w-full max-w-md rounded-[24px] border border-[#E8D8D1] bg-[#FFFCF9] p-7 text-center shadow-sm">
          <AlertTriangle className="mx-auto text-[#D85C3D]" size={30} />
          <h1 className="mt-4 text-xl font-semibold text-[#2A2825]"><I18nText>有声书暂时无法打开</I18nText></h1>
          <p className="mt-2 text-sm leading-6 text-[#77716B]">{player.loadError}</p>
          <div className="mt-6 flex justify-center gap-3">
            <Link href="/library" className="flex min-h-11 items-center rounded-xl border border-black/[0.08] bg-white px-4 text-sm font-medium text-[#4C4843]"><I18nText>返回书库</I18nText></Link>
            <button type="button" onClick={() => void player.retry()} className="flex min-h-11 items-center gap-2 rounded-xl bg-[#EF4D2F] px-4 text-sm font-semibold text-white"><RotateCcw size={16} /><I18nText>重试</I18nText></button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-[60dvh] items-center justify-center" role="status" aria-live="polite">
      <div className="text-center text-[#77716B]">
        <LoaderCircle size={28} className="mx-auto animate-spin text-[#EF4D2F] motion-reduce:animate-none" />
        <p className="mt-4 text-sm"><I18nText>正在返回图书详情…</I18nText></p>
      </div>
    </div>
  );
}

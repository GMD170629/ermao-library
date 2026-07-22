'use client';

import { AlertTriangle, LoaderCircle, RotateCcw } from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useRef } from 'react';
import { useAudioPlayback } from './audio-playback-provider';

export function AudioListenRedirect({ editionId }: { editionId: string }) {
  const player = useAudioPlayback();
  const router = useRouter();
  const searchParams = useSearchParams();
  const chapterId = searchParams.get('chapter')?.trim() || null;
  const trackParam = searchParams.get('track');
  const appliedTrackRef = useRef('');

  useEffect(() => {
    void player.loadEdition(editionId, {
      autoplay: false,
      chapterId: chapterId ?? undefined
    });
  }, [chapterId, editionId, player.loadEdition]);

  useEffect(() => {
    const bootstrap = player.bootstrap?.edition.id === editionId ? player.bootstrap : null;
    if (!bootstrap) return;
    const targetKey = `${editionId}:${trackParam ?? ''}`;
    if (!chapterId && trackParam !== null && appliedTrackRef.current !== targetKey) {
      const trackIndex = Number(trackParam);
      if (Number.isInteger(trackIndex) && trackIndex >= 0 && trackIndex < bootstrap.tracks.length) {
        player.selectTrack(trackIndex, false);
      }
      appliedTrackRef.current = targetKey;
    }
    router.replace(`/works/${encodeURIComponent(bootstrap.edition.workId)}?detailTab=AUDIOBOOK&editionId=${encodeURIComponent(bootstrap.edition.id)}`);
  }, [chapterId, editionId, player.bootstrap, player.selectTrack, router, trackParam]);

  const failed = player.pendingEditionId === editionId && Boolean(player.loadError);
  if (failed) {
    return (
      <div className="flex min-h-[60dvh] items-center justify-center px-4">
        <div className="w-full max-w-md rounded-[24px] border border-[#E8D8D1] bg-[#FFFCF9] p-7 text-center shadow-sm">
          <AlertTriangle className="mx-auto text-[#D85C3D]" size={30} />
          <h1 className="mt-4 text-xl font-semibold text-[#2A2825]">有声书暂时无法打开</h1>
          <p className="mt-2 text-sm leading-6 text-[#77716B]">{player.loadError}</p>
          <div className="mt-6 flex justify-center gap-3">
            <Link href="/library" className="flex min-h-11 items-center rounded-xl border border-black/[0.08] bg-white px-4 text-sm font-medium text-[#4C4843]">返回书库</Link>
            <button type="button" onClick={() => void player.retry()} className="flex min-h-11 items-center gap-2 rounded-xl bg-[#EF4D2F] px-4 text-sm font-semibold text-white"><RotateCcw size={16} />重试</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-[60dvh] items-center justify-center" role="status" aria-live="polite">
      <div className="text-center text-[#77716B]">
        <LoaderCircle size={28} className="mx-auto animate-spin text-[#EF4D2F] motion-reduce:animate-none" />
        <p className="mt-4 text-sm">正在返回图书详情…</p>
      </div>
    </div>
  );
}

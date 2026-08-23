import { Check } from 'lucide-react';

export type CoverReadingProgressState = Readonly<{
  value: number;
  roundedValue: number;
  visible: boolean;
  finished: boolean;
}>;

export function coverReadingProgressState(progress: number): CoverReadingProgressState {
  const value = Number.isFinite(progress) ? Math.max(0, Math.min(100, progress)) : 0;
  const roundedValue = Math.round(value);
  return {
    value,
    roundedValue,
    visible: roundedValue > 0,
    finished: value >= 100
  };
}

export function CoverReadingProgress({
  progress,
  surface
}: {
  progress: number;
  surface: 'bookshelf' | 'resource';
}) {
  const state = coverReadingProgressState(progress);
  if (!state.visible) return null;

  const isBookshelf = surface === 'bookshelf';
  return (
    <span
      data-cover-reading-progress="true"
      data-bookshelf-progress={isBookshelf ? 'true' : undefined}
      data-bookshelf-progress-state={isBookshelf ? (state.finished ? 'finished' : 'reading') : undefined}
      data-resource-progress={!isBookshelf ? 'true' : undefined}
      data-resource-progress-state={!isBookshelf ? (state.finished ? 'finished' : 'reading') : undefined}
      aria-hidden="true"
      className="pointer-events-none absolute inset-x-2 bottom-1.5 z-10 block h-[2px] rounded-full bg-[#8B837B]/30"
    >
      <span
        className="block h-full rounded-full bg-[#FF4F2A]"
        style={{ width: `${state.value}%` }}
      />
      {state.finished ? (
        <span
          data-bookshelf-progress-complete={isBookshelf ? 'true' : undefined}
          data-resource-progress-complete={!isBookshelf ? 'true' : undefined}
          className="absolute right-0 top-1/2 flex h-[11px] w-[11px] -translate-y-1/2 items-center justify-center rounded-full bg-[#FF4F2A] text-white"
        >
          <Check size={7} strokeWidth={3} />
        </span>
      ) : null}
    </span>
  );
}

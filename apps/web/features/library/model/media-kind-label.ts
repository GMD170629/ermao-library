import type { MediaKind } from '../../../types/book';

const MEDIA_KIND_ORDER: readonly MediaKind[] = ['EBOOK', 'COMIC', 'AUDIOBOOK'];

export function orderedMediaKinds(kinds: readonly MediaKind[]): MediaKind[] {
  const available = new Set(kinds);
  return MEDIA_KIND_ORDER.filter((kind) => available.has(kind));
}

export function mediaKindsLabel(kinds: readonly MediaKind[], locale: string): string {
  const chinese = locale.toLowerCase().startsWith('zh');
  const labels: Record<MediaKind, string> = chinese
    ? { EBOOK: '电子书', COMIC: '漫画', AUDIOBOOK: '有声书' }
    : { EBOOK: 'E-book', COMIC: 'Comic', AUDIOBOOK: 'Audiobook' };
  return orderedMediaKinds(kinds).map((kind) => labels[kind]).join(chinese ? '，' : ', ');
}

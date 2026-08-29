import type { ReaderFontFamily } from '@shuku/reader-core';
import { withBasePath } from '../../../../lib/base-path';

export type EpubFontResolution = {
  stack: string;
  source: 'system' | 'embedded' | 'fallback';
  embedded?: { family: string; url: string; release?: () => void };
};

type FontProfile = {
  systemFamilies: string[];
  generic: 'sans-serif' | 'serif';
  embeddedFamily: string;
  embeddedUrl: string;
};

const profiles: Record<ReaderFontFamily, FontProfile> = {
  pingfang: { systemFamilies: ['PingFang SC', 'Hiragino Sans GB'], generic: 'sans-serif', embeddedFamily: 'Shuku Reader Sans', embeddedUrl: withBasePath('/fonts/reader/sans.woff2') },
  songti: { systemFamilies: ['Songti SC', 'STSong', 'SimSun'], generic: 'serif', embeddedFamily: 'Shuku Reader Songti', embeddedUrl: withBasePath('/fonts/reader/songti.woff2') },
  kaiti: { systemFamilies: ['Kaiti SC', 'STKaiti', 'KaiTi'], generic: 'serif', embeddedFamily: 'Shuku Reader Kaiti', embeddedUrl: withBasePath('/fonts/reader/kaiti.woff2') }
};

function quotedStack(families: string[], generic: FontProfile['generic']) {
  return [...families.map((family) => `"${family}"`), generic].join(', ');
}

export function fallbackEpubFont(family: ReaderFontFamily): EpubFontResolution {
  const profile = profiles[family];
  return { stack: quotedStack(profile.systemFamilies, profile.generic), source: 'fallback' };
}

export type ResolveEpubFontOptions = {
  signal: AbortSignal;
  fetch?: typeof globalThis.fetch;
  fontSet?: Pick<FontFaceSet, 'check'> | null;
  FontFace?: typeof globalThis.FontFace;
  document?: Document | null;
  timeoutMs?: number;
  createObjectURL?: (blob: Blob) => string;
  revokeObjectURL?: (url: string) => void;
};

function canvasDetectsFont(document: Document, family: string) {
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('2d');
  if (!context) return false;
  const sample = 'mmmmmmmmmmWWWWW汉字';
  return ['monospace', 'sans-serif', 'serif'].some((baseline) => {
    context.font = `72px ${baseline}`;
    const fallbackWidth = context.measureText(sample).width;
    context.font = `72px "${family}", ${baseline}`;
    return Math.abs(context.measureText(sample).width - fallbackWidth) > 0.01;
  });
}

function systemFontAvailable(family: string, options: ResolveEpubFontOptions) {
  if (options.fontSet) {
    try {
      return options.fontSet.check(`16px "${family}"`, '汉字');
    } catch {
      return false;
    }
  }
  try {
    return options.document ? canvasDetectsFont(options.document, family) : false;
  } catch {
    return false;
  }
}

function combineSignals(first: AbortSignal, second: AbortSignal) {
  if (typeof AbortSignal.any === 'function') return AbortSignal.any([first, second]);
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (first.aborted || second.aborted) controller.abort();
  else {
    first.addEventListener('abort', abort, { once: true });
    second.addEventListener('abort', abort, { once: true });
  }
  return controller.signal;
}

export async function resolveEpubFont(family: ReaderFontFamily, options: ResolveEpubFontOptions): Promise<EpubFontResolution> {
  const profile = profiles[family];
  const systemFamily = profile.systemFamilies.find((candidate) => systemFontAvailable(candidate, options));
  if (systemFamily) {
    return { stack: quotedStack([systemFamily, ...profile.systemFamilies.filter((candidate) => candidate !== systemFamily)], profile.generic), source: 'system' };
  }

  const timeoutController = new AbortController();
  const timeout = setTimeout(() => timeoutController.abort(), options.timeoutMs ?? 10_000);
  const signal = combineSignals(options.signal, timeoutController.signal);
  try {
    const response = await (options.fetch ?? globalThis.fetch)(profile.embeddedUrl, { signal, cache: 'force-cache' });
    if (!response.ok) throw new Error(`Reader font failed (${response.status})`);
    const bytes = await response.arrayBuffer();
    if (options.FontFace) await new options.FontFace(profile.embeddedFamily, bytes).load();
    if (options.signal.aborted) throw new DOMException('The operation was aborted', 'AbortError');
    const objectUrl = options.createObjectURL?.(new Blob([bytes], { type: 'font/woff2' }));
    let released = false;
    return {
      stack: `"${profile.embeddedFamily}", ${quotedStack(profile.systemFamilies, profile.generic)}`,
      source: 'embedded',
      embedded: {
        family: profile.embeddedFamily,
        url: objectUrl ?? profile.embeddedUrl,
        release: objectUrl && options.revokeObjectURL
          ? () => {
            if (released) return;
            released = true;
            options.revokeObjectURL?.(objectUrl);
          }
          : undefined
      }
    };
  } catch (reason) {
    if (options.signal.aborted) throw reason;
    return fallbackEpubFont(family);
  } finally {
    clearTimeout(timeout);
  }
}

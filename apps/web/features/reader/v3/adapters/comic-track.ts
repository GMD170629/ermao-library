import type { PagedTrackDriver, PagedTrackDriverSnapshot, PageStep } from '../paged-track/paged-track-types';
import { comicImageSizing, comicPageSlotSizing, type ComicImageFit, type ComicPageMeta } from './comic-model';
import { normalizeLocale } from '../../../../i18n/config';
import { translateMessage } from '../../../../i18n/messages';

export type ComicTrackPage = ComicPageMeta & {
  url: string;
  error?: string;
};

export type ComicTrackSpread = {
  anchor: number;
  pages: ComicTrackPage[];
};

export type ComicTrackView = {
  previous: ComicTrackSpread | null;
  current: ComicTrackSpread | null;
  next: ComicTrackSpread | null;
  direction: 'ltr' | 'rtl';
  mode: 'single' | 'double';
  imageFit: ComicImageFit;
  zoom: number;
  pageWidth: number;
  pageGap?: 0 | 8 | 16 | 24;
  reducedMotion: boolean;
  error?: string;
};

export type ComicTrackSource = {
  getView: () => ComicTrackView;
  prepare: (step: PageStep, signal: AbortSignal) => Promise<boolean>;
  promote: (step: PageStep, signal: AbortSignal) => Promise<void> | void;
  retry: (page: number) => void;
};

type ComicTrackSlot = 'previous' | 'current' | 'next';

function abortError() {
  return new DOMException('The operation was aborted', 'AbortError');
}

function throwIfAborted(signal: AbortSignal) {
  if (signal.aborted) throw abortError();
}

function frameRequest(callback: FrameRequestCallback) {
  if (typeof requestAnimationFrame === 'function') return requestAnimationFrame(callback);
  return setTimeout(() => callback(Date.now()), 16) as unknown as number;
}

function frameCancel(handle: number) {
  if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(handle);
  else clearTimeout(handle);
}

function now() {
  return typeof performance === 'object' && typeof performance.now === 'function' ? performance.now() : Date.now();
}

function easeOutQuint(value: number) {
  return 1 - Math.pow(1 - value, 5);
}

function spreadKey(spread: ComicTrackSpread | null, view: ComicTrackView, role: ComicTrackSlot) {
  if (!spread) return role === 'current' && view.error ? `error:${view.error}` : 'empty';
  return JSON.stringify({
    anchor: spread.anchor,
    fit: view.imageFit,
    mode: view.mode,
    pages: spread.pages.map((page) => [page.pageIndex, page.url, page.safetyError?.ruleId]),
    zoom: view.zoom,
    pageWidth: view.pageWidth,
    pageGap: view.pageGap ?? 0
  });
}

/**
 * Persistent three-slot comic track. The source owns page identity; this
 * class only owns presentation, physical direction and deterministic motion.
 */
export class ComicSpreadTrackDriver implements PagedTrackDriver {
  private readonly container: HTMLElement;
  private readonly document: Document;
  private readonly source: ComicTrackSource;
  private readonly viewport: HTMLElement;
  private readonly track: HTMLElement;
  private slots: Record<ComicTrackSlot, HTMLElement>;
  private readonly renderedKeys = new WeakMap<HTMLElement, string>();
  private animationHandle: number | null = null;
  private animationTimeout: ReturnType<typeof setTimeout> | null = null;
  private rejectAnimation: ((reason: unknown) => void) | null = null;
  private removeAnimationAbortListener: (() => void) | null = null;

  constructor(container: HTMLElement, source: ComicTrackSource) {
    const ownerDocument = container.ownerDocument ?? (typeof document === 'object' ? document : null);
    if (!ownerDocument) throw new Error('comic-track-document-unavailable');
    this.container = container;
    this.document = ownerDocument;
    this.source = source;
    this.viewport = this.document.createElement('div');
    this.track = this.document.createElement('div');
    this.slots = {
      previous: this.createSlot('previous'),
      current: this.createSlot('current'),
      next: this.createSlot('next')
    };
    this.viewport.dataset.comicViewport = 'true';
    this.track.dataset.comicTrack = 'true';
    Object.assign(this.viewport.style, {
      height: '100%',
      overflow: 'hidden',
      overscrollBehavior: 'contain',
      position: 'relative',
      width: '100%'
    });
    Object.assign(this.track.style, {
      display: 'flex',
      height: '100%',
      width: '100%'
    });
    this.viewport.append(this.track);
    this.mount();
  }

  getViewportElement() {
    return this.viewport;
  }

  /** Exposed for focused DOM tests and reader diagnostics. */
  getSlotElement(slot: ComicTrackSlot) {
    return this.slots[slot];
  }

  snapshot(): PagedTrackDriverSnapshot {
    const view = this.source.getView();
    return {
      phase: 'idle',
      readingDirection: view.direction,
      viewportWidth: this.viewport.clientWidth || this.container.clientWidth,
      hasPrevious: Boolean(view.previous),
      hasNext: Boolean(view.next),
      reducedMotion: view.reducedMotion
    };
  }

  async prepare(step: PageStep, signal: AbortSignal) {
    throwIfAborted(signal);
    const prepared = await this.source.prepare(step, signal);
    throwIfAborted(signal);
    this.render(this.source.getView());
    return prepared;
  }

  setLogicalOffset(offsetPx: number) {
    const view = this.source.getView();
    const center = this.viewportWidth();
    const physicalSign = view.direction === 'rtl' ? -1 : 1;
    this.viewport.scrollLeft = Math.max(0, Math.min(center * 2, center + offsetPx * physicalSign));
  }

  animateTo(target: -1 | 0 | 1, durationMs: number, signal: AbortSignal) {
    this.stopAnimation(abortError());
    throwIfAborted(signal);
    const view = this.source.getView();
    const width = this.viewportWidth();
    const physicalSign = view.direction === 'rtl' ? -1 : 1;
    const destination = Math.max(0, Math.min(width * 2, width + target * width * physicalSign));
    const start = this.viewport.scrollLeft;
    if (durationMs <= 0 || Math.abs(destination - start) < 0.5) {
      this.viewport.scrollLeft = destination;
      return Promise.resolve();
    }
    const startedAt = now();
    return new Promise<void>((resolve, reject) => {
      let settled = false;
      this.rejectAnimation = reject;
      const abort = () => this.stopAnimation(abortError());
      signal.addEventListener('abort', abort, { once: true });
      this.removeAnimationAbortListener = () => signal.removeEventListener('abort', abort);
      const finish = () => {
        if (settled) return;
        settled = true;
        if (this.animationHandle !== null) frameCancel(this.animationHandle);
        this.animationHandle = null;
        if (this.animationTimeout !== null) clearTimeout(this.animationTimeout);
        this.animationTimeout = null;
        this.removeAnimationAbortListener?.();
        this.removeAnimationAbortListener = null;
        this.rejectAnimation = null;
        this.viewport.scrollLeft = destination;
        resolve();
      };
      const tick = () => {
        if (signal.aborted) {
          abort();
          return;
        }
        const progress = Math.min(1, (now() - startedAt) / durationMs);
        this.viewport.scrollLeft = start + (destination - start) * easeOutQuint(progress);
        if (progress >= 1) finish();
        else this.animationHandle = frameRequest(tick);
      };
      this.animationTimeout = setTimeout(finish, durationMs + 96);
      this.animationHandle = frameRequest(tick);
    });
  }

  async promote(step: PageStep, signal: AbortSignal) {
    throwIfAborted(signal);
    await this.source.promote(step, signal);
    throwIfAborted(signal);
    this.rotateSlots(step);
    this.render(this.source.getView());
    this.recenter(true);
  }

  recenter(resetVerticalToStart = false) {
    this.stopAnimation(abortError());
    this.viewport.scrollLeft = this.viewportWidth();
    const current = this.slots.current;
    if (this.source.getView().zoom > 1) {
      current.scrollLeft = Math.max(0, (current.scrollWidth - current.clientWidth) / 2);
      current.scrollTop = resetVerticalToStart
        ? 0
        : Math.max(0, (current.scrollHeight - current.clientHeight) / 2);
    } else {
      current.scrollLeft = 0;
      current.scrollTop = 0;
    }
  }

  cancel() {
    this.stopAnimation(abortError());
  }

  render(view = this.source.getView()) {
    this.mount();
    Object.assign(this.container.style, {
      display: 'block',
      overflow: 'hidden',
      touchAction: view.zoom > 1 ? 'pan-x pan-y' : 'pan-y'
    });
    this.viewport.style.touchAction = view.zoom > 1 ? 'pan-x pan-y' : 'pan-y';
    this.orderSlots(view.direction);
    this.renderSlot('previous', view.previous, view);
    this.renderSlot('current', view.current, view);
    this.renderSlot('next', view.next, view);
  }

  reset() {
    this.cancel();
    this.renderedKeys.delete(this.slots.previous);
    this.renderedKeys.delete(this.slots.current);
    this.renderedKeys.delete(this.slots.next);
    this.slots.previous.replaceChildren();
    this.slots.current.replaceChildren();
    this.slots.next.replaceChildren();
    this.mount();
    this.recenter();
  }

  destroy() {
    this.cancel();
    this.viewport.remove();
  }

  private mount() {
    if (this.viewport.parentElement !== this.container) this.container.append(this.viewport);
  }

  private createSlot(role: ComicTrackSlot) {
    const slot = this.document.createElement('div');
    slot.dataset.comicSpreadSlot = role;
    Object.assign(slot.style, {
      alignItems: 'stretch',
      boxSizing: 'border-box',
      flex: '0 0 100%',
      height: '100%',
      minWidth: '100%',
      overflow: 'hidden',
      scrollSnapAlign: 'center',
      width: '100%'
    });
    return slot;
  }

  private viewportWidth() {
    return Math.max(1, this.viewport.clientWidth || this.container.clientWidth || 1);
  }

  private orderSlots(direction: 'ltr' | 'rtl') {
    const ordered = direction === 'rtl'
      ? [this.slots.next, this.slots.current, this.slots.previous]
      : [this.slots.previous, this.slots.current, this.slots.next];
    if (this.track.children[0] === ordered[0] && this.track.children[1] === ordered[1] && this.track.children[2] === ordered[2]) return;
    this.track.append(...ordered);
  }

  private rotateSlots(step: PageStep) {
    const previous = this.slots.previous;
    const current = this.slots.current;
    const next = this.slots.next;
    this.slots = step === 1
      ? { previous: current, current: next, next: previous }
      : { previous: next, current: previous, next: current };
    (Object.keys(this.slots) as ComicTrackSlot[]).forEach((role) => {
      this.slots[role].dataset.comicSpreadSlot = role;
    });
  }

  private renderSlot(role: ComicTrackSlot, spread: ComicTrackSpread | null, view: ComicTrackView) {
    const slot = this.slots[role];
    slot.dataset.comicSpreadSlot = role;
    if (spread) slot.dataset.comicSpreadAnchor = String(spread.anchor);
    else delete slot.dataset.comicSpreadAnchor;
    slot.style.overflow = role === 'current' && view.zoom > 1 ? 'auto' : 'hidden';
    const key = spreadKey(spread, view, role);
    if (this.renderedKeys.get(slot) === key) {
      const frame = slot.children[0] as HTMLElement | undefined;
      if (frame) {
        if (role === 'current') frame.dataset.comicView = 'true';
        else delete frame.dataset.comicView;
      }
      return;
    }
    this.renderedKeys.set(slot, key);
    slot.replaceChildren();
    if (!spread && !(view.error && role === 'current')) return;
    const frame = this.document.createElement('div');
    if (role === 'current') frame.dataset.comicView = 'true';
    Object.assign(frame.style, {
      alignItems: 'center',
      boxSizing: 'border-box',
      display: 'flex',
      gap: `${view.pageGap ?? 0}px`,
      height: `${view.zoom * 100}%`,
      justifyContent: 'center',
      margin: view.zoom > 1 ? 'auto' : '0',
      minHeight: '100%',
      minWidth: '100%',
      overflow: 'visible',
      padding: '24px 16px',
      width: `${view.zoom * 100}%`
    });
    frame.style.maxWidth = `${view.pageWidth * view.zoom}px`;
    if (view.error && role === 'current' && !spread?.pages.length) {
      const message = this.document.createElement('div');
      message.setAttribute('role', 'alert');
      message.textContent = view.error;
      message.style.color = '#ef4444';
      frame.append(message);
    } else {
      const pages = spread?.pages ?? [];
      const layoutMode = view.mode === 'double' && pages.length === 2 ? 'double' : 'single';
      pages.forEach((page, index) => {
        const pageSlot = this.document.createElement('div');
        pageSlot.dataset.comicPageIndex = String(page.pageIndex);
        const sizing = comicPageSlotSizing(layoutMode);
        Object.assign(pageSlot.style, {
          alignItems: 'center',
          boxSizing: 'border-box',
          display: 'flex',
          flex: sizing.flex,
          height: '100%',
          justifyContent: layoutMode === 'double' ? (index === 0 ? 'flex-end' : 'flex-start') : 'center',
          maxWidth: sizing.maxWidth,
          minWidth: '0',
          overflow: 'hidden',
          position: 'relative',
          width: sizing.width
        });
        const locale = normalizeLocale(this.document.documentElement.lang);
        const image = this.document.createElement('img');
        const placeholder = this.document.createElement('div');
        placeholder.dataset.comicPagePlaceholder = String(page.pageIndex);
        placeholder.setAttribute('role', 'status');
        placeholder.textContent = translateMessage(locale, '加载中');
        Object.assign(placeholder.style, {
          alignItems: 'center',
          display: 'flex',
          height: '100%',
          justifyContent: 'center',
          opacity: '0.7',
          padding: '24px',
          position: 'absolute',
          inset: '0'
        });
        if (page.safetyError) {
          placeholder.dataset.readerSafetyRuleId = page.safetyError.ruleId;
          placeholder.dataset.readerSafetyErrorCode = page.safetyError.code;
          placeholder.setAttribute('role', 'alert');
          placeholder.textContent = translateMessage(locale, '漫画页面因安全策略无法显示。');
          pageSlot.append(placeholder);
          frame.append(pageSlot);
          return;
        }
        image.alt = translateMessage(locale, '第 {value0} 页', { value0: page.pageIndex + 1 });
        image.decoding = 'async';
        image.draggable = false;
        image.style.visibility = 'hidden';
        Object.assign(image.style, comicImageSizing(view.imageFit, layoutMode));
        const cleanup = () => {
          image.removeEventListener('load', handleLoad);
          image.removeEventListener('error', handleError);
        };
        const handleLoad = () => {
          cleanup();
          image.style.visibility = 'visible';
          placeholder.remove();
        };
        const handleError = () => {
          cleanup();
          const failure = this.document.createElement('div');
          failure.setAttribute('role', 'alert');
          const message = this.document.createElement('p');
          message.textContent = translateMessage(locale, '漫画页面加载失败，浏览器未提供具体原因。');
          const retry = this.document.createElement('button');
          retry.type = 'button';
          retry.textContent = translateMessage(locale, '重试');
          retry.addEventListener('click', () => this.source.retry(page.pageIndex), { once: true });
          failure.append(message, retry);
          placeholder.replaceChildren(failure);
        };
        image.addEventListener('load', handleLoad, { once: true });
        image.addEventListener('error', handleError, { once: true });
        pageSlot.append(image, placeholder);
        image.src = page.url;
        if (image.complete && image.naturalWidth > 0) handleLoad();
        frame.append(pageSlot);
      });
    }
    slot.append(frame);
  }

  private stopAnimation(reason: unknown) {
    if (this.animationHandle !== null) frameCancel(this.animationHandle);
    this.animationHandle = null;
    if (this.animationTimeout !== null) clearTimeout(this.animationTimeout);
    this.animationTimeout = null;
    this.removeAnimationAbortListener?.();
    this.removeAnimationAbortListener = null;
    const reject = this.rejectAnimation;
    this.rejectAnimation = null;
    reject?.(reason);
  }
}

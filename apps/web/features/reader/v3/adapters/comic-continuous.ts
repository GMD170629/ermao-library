import { comicImageSizing, type ComicImageFit } from './comic-model';
import type { ComicTrackPage } from './comic-track';
import { normalizeLocale } from '../../../../i18n/config';
import { translateMessage } from '../../../../i18n/messages';
import { continuousItemAtReadingLine } from './continuous-layout';

export type ComicContinuousView = {
  currentPage: number;
  pageCount: number;
  imageFit: ComicImageFit;
  zoom: number;
  pageWidth: number;
  pages: ComicTrackPage[];
};

type ComicPageSlot = {
  element: HTMLElement;
  contentKey: string;
  image: HTMLImageElement | null;
  loaded: boolean;
};

function pageHeight(page: ComicTrackPage, availableWidth: number, viewportHeight: number) {
  const width = typeof page.width === 'number' && page.width > 0 ? page.width : null;
  const height = typeof page.height === 'number' && page.height > 0 ? page.height : null;
  const ratioHeight = width && height ? availableWidth * height / width : viewportHeight * 0.9;
  return Math.max(240, Math.round(ratioHeight));
}

export class ComicContinuousController {
  private readonly container: HTMLElement;
  private readonly root: HTMLElement;
  private readonly document: Document;
  private readonly onCurrentPage: (page: number) => void;
  private readonly onRetryPage: (page: number) => void;
  private readonly slots = new Map<number, ComicPageSlot>();
  private readonly preloadObserver: IntersectionObserver | null;
  private currentPage = 1;
  private programmaticScroll = false;

  constructor(
    container: HTMLElement,
    onCurrentPage: (page: number) => void,
    onRetryPage: (page: number) => void
  ) {
    this.container = container;
    this.document = container.ownerDocument;
    this.onCurrentPage = onCurrentPage;
    this.onRetryPage = onRetryPage;
    this.root = this.document.createElement('div');
    this.root.dataset.comicContinuous = 'true';
    Object.assign(this.root.style, {
      display: 'none',
      height: '100%',
      overflowX: 'hidden',
      overflowY: 'auto',
      overscrollBehavior: 'contain',
      scrollBehavior: 'auto',
      width: '100%'
    });
    this.root.addEventListener('scroll', this.handleScroll, { passive: true });
    container.append(this.root);
    const IntersectionObserverConstructor = this.document.defaultView?.IntersectionObserver
      ?? globalThis.IntersectionObserver;
    const ImageElementConstructor = this.document.defaultView?.HTMLImageElement;
    this.preloadObserver = typeof IntersectionObserverConstructor === 'function'
      && typeof ImageElementConstructor === 'function'
      ? new IntersectionObserverConstructor((entries, observer) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting || !(entry.target instanceof ImageElementConstructor)) return;
            const image = entry.target;
            image.loading = 'eager';
            image.dataset.comicContinuousPreloaded = 'true';
            observer.unobserve(image);
          });
        }, {
          root: this.root,
          rootMargin: '200% 0px',
          threshold: 0
        })
      : null;
  }

  setEnabled(enabled: boolean) {
    if (this.root.parentElement !== this.container) this.container.append(this.root);
    this.root.style.display = enabled ? 'block' : 'none';
  }

  render(view: ComicContinuousView, scrollToCurrentPage = false) {
    const hadSlots = this.slots.size > 0;
    this.currentPage = view.currentPage;
    this.root.dataset.comicContinuousCurrent = String(view.currentPage);
    this.root.style.paddingBlock = '0px';
    const viewportWidth = Math.max(1, this.root.clientWidth || this.container.clientWidth);
    const availableWidth = Math.max(1, Math.round(Math.min(view.pageWidth, viewportWidth) * view.zoom));
    this.root.style.overflowX = availableWidth > viewportWidth ? 'auto' : 'hidden';
    const knownPages = new Set(view.pages.map((page) => page.pageIndex));
    for (const [page, slot] of this.slots) {
      if (knownPages.has(page)) continue;
      slot.element.remove();
      this.slots.delete(page);
    }
    view.pages.forEach((page) => {
      const slot = this.slotFor(page.pageIndex);
      slot.element.style.maxWidth = 'none';
      slot.element.style.width = `${availableWidth}px`;
      slot.element.style.marginInline = 'auto';
      slot.element.style.marginBlockEnd = '0px';
      if (!slot.loaded) {
        slot.element.style.minHeight = `${pageHeight(page, availableWidth, this.root.clientHeight)}px`;
      }
      this.renderSlot(slot, page, view);
      if (slot.element.parentElement !== this.root) this.root.append(slot.element);
    });
    if (scrollToCurrentPage || !hadSlots) this.scrollToPage(view.currentPage);
  }

  scrollToPage(page: number) {
    const target = this.slots.get(page)?.element;
    if (!target) return;
    this.programmaticScroll = true;
    this.root.scrollTop = Math.max(0, target.offsetTop);
    this.document.defaultView?.requestAnimationFrame?.(() => { this.programmaticScroll = false; });
  }

  destroy() {
    this.root.removeEventListener('scroll', this.handleScroll);
    this.preloadObserver?.disconnect();
    this.slots.clear();
    this.root.remove();
  }

  private slotFor(page: number) {
    const existing = this.slots.get(page);
    if (existing) return existing;
    const element = this.document.createElement('section');
    element.dataset.comicContinuousPage = String(page);
    Object.assign(element.style, {
      alignItems: 'center',
      display: 'flex',
      justifyContent: 'center',
      overflow: 'visible',
      position: 'relative',
      width: '100%'
    });
    const slot = { element, contentKey: '', image: null, loaded: false };
    this.slots.set(page, slot);
    return slot;
  }

  private renderSlot(slot: ComicPageSlot, page: ComicTrackPage, view: ComicContinuousView) {
    const contentKey = page.safetyError
      ? `blocked:${page.safetyError.ruleId}`
      : page.url
        ? `ready:${page.url}`
        : page.error
          ? `failed:${page.error}`
          : 'placeholder';
    if (slot.contentKey !== contentKey) {
      if (slot.image) this.preloadObserver?.unobserve(slot.image);
      slot.contentKey = contentKey;
      slot.image = null;
      slot.loaded = false;
      if (page.safetyError) {
        this.renderFailure(
          slot,
          page.pageIndex,
          translateMessage(normalizeLocale(this.document.documentElement.lang), '漫画页面因安全策略无法显示。'),
          false
        );
        slot.element.dataset.readerSafetyRuleId = page.safetyError.ruleId;
        slot.element.dataset.readerSafetyErrorCode = page.safetyError.code;
      } else if (page.url) {
        const image = this.document.createElement('img');
        image.alt = String(page.pageIndex);
        image.decoding = 'async';
        image.loading = 'lazy';
        image.addEventListener('load', () => {
          if (slot.image !== image) return;
          this.preloadObserver?.unobserve(image);
          slot.loaded = true;
          slot.element.dataset.comicContinuousLoaded = 'true';
          slot.element.style.minHeight = '0px';
        }, { once: true });
        image.addEventListener('error', () => {
          if (slot.image !== image) return;
          this.preloadObserver?.unobserve(image);
          slot.loaded = false;
          delete slot.element.dataset.comicContinuousLoaded;
          this.renderFailure(slot, page.pageIndex, translateMessage(
            normalizeLocale(this.document.documentElement.lang),
            '漫画页面加载失败，浏览器未提供具体原因。'
          ));
        }, { once: true });
        slot.image = image;
        image.src = page.url;
        slot.element.replaceChildren(image);
        this.preloadObserver?.observe(image);
      } else if (page.error) {
        this.renderFailure(slot, page.pageIndex, page.error);
      } else {
        slot.element.replaceChildren();
      }
    }
    if (slot.image) {
      Object.assign(slot.image.style, comicImageSizing(view.imageFit));
      slot.image.style.transform = '';
      slot.image.style.transformOrigin = '';
      if (slot.image.complete && slot.image.naturalWidth > 0) {
        slot.loaded = true;
        slot.element.dataset.comicContinuousLoaded = 'true';
        slot.element.style.minHeight = '0px';
      }
    }
  }

  private renderFailure(slot: ComicPageSlot, page: number, messageText: string, retryable = true) {
    const failure = this.document.createElement('div');
    failure.setAttribute('role', 'alert');
    const message = this.document.createElement('p');
    message.textContent = messageText;
    failure.append(message);
    if (retryable) {
      const retry = this.document.createElement('button');
      retry.type = 'button';
      retry.textContent = translateMessage(normalizeLocale(this.document.documentElement.lang), '重试本页');
      retry.addEventListener('click', () => this.onRetryPage(page));
      failure.append(retry);
    }
    slot.element.replaceChildren(failure);
  }

  private readonly handleScroll = () => {
    if (this.programmaticScroll) return;
    const pages = Array.from(this.slots.values(), (slot) => slot.element);
    const index = continuousItemAtReadingLine(pages, this.root.scrollTop, this.root.clientHeight);
    const page = Number(pages[index]?.dataset.comicContinuousPage);
    if (!Number.isFinite(page) || page === this.currentPage) return;
    this.currentPage = page;
    this.root.dataset.comicContinuousCurrent = String(page);
    this.onCurrentPage(page);
  };
}

import { comicImageSizing, type ComicImageFit } from './comic-model';
import type { ComicTrackPage } from './comic-track';
import { normalizeLocale } from '../../../../i18n/config';
import { translateMessage } from '../../../../i18n/messages';
import {
  captureContinuousAnchor,
  continuousItemAtReadingLine,
  restoreContinuousAnchor
} from './continuous-layout';

export type ComicContinuousView = {
  currentPage: number;
  pageCount: number;
  pageGap: 0 | 8 | 16 | 24;
  imageFit: ComicImageFit;
  zoom: number;
  pages: ComicTrackPage[];
};

type ComicPageSlot = {
  element: HTMLElement;
  contentKey: string;
  image: HTMLImageElement | null;
};

function pageHeight(page: ComicTrackPage, availableWidth: number, viewportHeight: number, zoom: number) {
  const width = typeof page.width === 'number' && page.width > 0 ? page.width : null;
  const height = typeof page.height === 'number' && page.height > 0 ? page.height : null;
  const ratioHeight = width && height ? availableWidth * height / width : viewportHeight * 0.9;
  return Math.max(240, Math.round(ratioHeight * zoom));
}

export class ComicContinuousController {
  private readonly container: HTMLElement;
  private readonly root: HTMLElement;
  private readonly document: Document;
  private readonly onCurrentPage: (page: number) => void;
  private readonly onRetryPage: (page: number) => void;
  private readonly slots = new Map<number, ComicPageSlot>();
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
  }

  setEnabled(enabled: boolean) {
    if (this.root.parentElement !== this.container) this.container.append(this.root);
    this.root.style.display = enabled ? 'block' : 'none';
  }

  render(view: ComicContinuousView, preserveAnchor = true) {
    const anchor = preserveAnchor ? this.captureAnchor() : null;
    this.currentPage = view.currentPage;
    this.root.dataset.comicContinuousCurrent = String(view.currentPage);
    this.root.style.paddingBlock = `${view.pageGap}px`;
    const availableWidth = Math.max(1, this.root.clientWidth || this.container.clientWidth);
    const knownPages = new Set(view.pages.map((page) => page.pageIndex));
    for (const [page, slot] of this.slots) {
      if (knownPages.has(page)) continue;
      slot.element.remove();
      this.slots.delete(page);
    }
    view.pages.forEach((page) => {
      const slot = this.slotFor(page.pageIndex);
      slot.element.style.marginBlockEnd = `${view.pageGap}px`;
      slot.element.style.minHeight = `${pageHeight(page, availableWidth, this.root.clientHeight, view.zoom)}px`;
      this.renderSlot(slot, page, view);
      if (slot.element.parentElement !== this.root) this.root.append(slot.element);
    });
    this.restoreAnchor(anchor);
    if (!preserveAnchor || !anchor) this.scrollToPage(view.currentPage);
  }

  scrollToPage(page: number) {
    const target = this.slots.get(page)?.element;
    if (!target) return;
    this.programmaticScroll = true;
    this.root.scrollTop = Math.max(0, target.offsetTop);
    this.document.defaultView?.requestAnimationFrame(() => { this.programmaticScroll = false; });
  }

  destroy() {
    this.root.removeEventListener('scroll', this.handleScroll);
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
      overflow: 'hidden',
      position: 'relative',
      width: '100%'
    });
    const slot = { element, contentKey: '', image: null };
    this.slots.set(page, slot);
    return slot;
  }

  private renderSlot(slot: ComicPageSlot, page: ComicTrackPage, view: ComicContinuousView) {
    const contentKey = page.url ? `ready:${page.url}` : page.error ? `failed:${page.error}` : 'placeholder';
    if (slot.contentKey !== contentKey) {
      slot.contentKey = contentKey;
      slot.image = null;
      if (page.url) {
        const image = this.document.createElement('img');
        image.src = page.url;
        image.alt = String(page.pageIndex);
        image.decoding = 'async';
        image.addEventListener('load', () => this.restoreAnchor(this.captureAnchor()), { once: true });
        slot.image = image;
        slot.element.replaceChildren(image);
      } else if (page.error) {
        const failure = this.document.createElement('div');
        failure.setAttribute('role', 'alert');
        const message = this.document.createElement('p');
        message.textContent = page.error;
        const retry = this.document.createElement('button');
        retry.type = 'button';
        retry.textContent = translateMessage(normalizeLocale(this.document.documentElement.lang), '重试本页');
        retry.addEventListener('click', () => this.onRetryPage(page.pageIndex));
        failure.append(message, retry);
        slot.element.replaceChildren(failure);
      } else {
        slot.element.replaceChildren();
      }
    }
    if (slot.image) {
      Object.assign(slot.image.style, comicImageSizing(view.imageFit));
      slot.image.style.transform = `scale(${view.zoom})`;
      slot.image.style.transformOrigin = 'top center';
    }
  }

  private captureAnchor() {
    const items = Array.from(this.slots.values(), (slot) => slot.element);
    return captureContinuousAnchor(
      this.root,
      items,
      (item) => item.dataset.comicContinuousPage
    );
  }

  private restoreAnchor(anchor: ReturnType<typeof captureContinuousAnchor>) {
    restoreContinuousAnchor(
      this.root,
      Array.from(this.slots.values(), (slot) => slot.element),
      anchor,
      (item) => item.dataset.comicContinuousPage
    );
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

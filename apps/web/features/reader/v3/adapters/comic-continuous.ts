import { comicImageSizing, type ComicImageFit } from './comic-model';
import type { ComicTrackPage } from './comic-track';

export type ComicContinuousView = {
  currentPage: number;
  pageCount: number;
  pageGap: 0 | 8 | 16 | 24;
  imageFit: ComicImageFit;
  zoom: number;
  pages: ComicTrackPage[];
};

export class ComicContinuousController {
  private readonly container: HTMLElement;
  private readonly root: HTMLElement;
  private readonly document: Document;
  private readonly onCurrentPage: (page: number) => void;
  private currentPage = 1;
  private programmaticScroll = false;

  constructor(container: HTMLElement, onCurrentPage: (page: number) => void) {
    this.container = container;
    this.document = container.ownerDocument;
    this.onCurrentPage = onCurrentPage;
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
    const anchor = preserveAnchor ? this.anchorOffset(view.currentPage) : null;
    this.currentPage = view.currentPage;
    this.root.style.paddingBlock = `${view.pageGap}px`;
    const pageElements = view.pages.map((page) => {
      const wrapper = this.document.createElement('div');
      wrapper.dataset.comicContinuousPage = String(page.pageIndex);
      Object.assign(wrapper.style, {
        alignItems: 'center',
        display: 'flex',
        justifyContent: 'center',
        marginBlockEnd: `${view.pageGap}px`,
        minHeight: 'min(72vh, 900px)',
        overflow: 'hidden',
        width: '100%'
      });
      if (page.url) {
        const image = this.document.createElement('img');
        image.src = page.url;
        image.alt = String(page.pageIndex);
        image.decoding = 'async';
        Object.assign(image.style, comicImageSizing(view.imageFit));
        image.style.transform = `scale(${view.zoom})`;
        image.style.transformOrigin = 'top center';
        wrapper.append(image);
      } else {
        wrapper.textContent = page.error ?? '…';
      }
      return wrapper;
    });
    this.root.replaceChildren(...pageElements);
    const target = this.pageElement(view.currentPage);
    this.programmaticScroll = true;
    if (target) {
      if (anchor === null) target.scrollIntoView({ block: 'start' });
      else this.root.scrollTop = Math.max(0, target.offsetTop - anchor);
    }
    this.document.defaultView?.requestAnimationFrame(() => { this.programmaticScroll = false; });
  }

  scrollToPage(page: number) {
    const target = this.pageElement(page);
    if (!target) return;
    this.programmaticScroll = true;
    target.scrollIntoView({ block: 'start' });
    this.document.defaultView?.requestAnimationFrame(() => { this.programmaticScroll = false; });
  }

  destroy() {
    this.root.removeEventListener('scroll', this.handleScroll);
    this.root.remove();
  }

  private pageElement(page: number) {
    return Array.from(this.root.querySelectorAll<HTMLElement>('[data-comic-continuous-page]'))
      .find((element) => Number(element.dataset.comicContinuousPage) === page) ?? null;
  }

  private anchorOffset(page: number) {
    const element = this.pageElement(page);
    return element ? element.offsetTop - this.root.scrollTop : null;
  }

  private readonly handleScroll = () => {
    if (this.programmaticScroll) return;
    const pages = Array.from(this.root.querySelectorAll<HTMLElement>('[data-comic-continuous-page]'));
    const closest = pages.reduce<HTMLElement | null>((best, element) => {
      if (!best) return element;
      return Math.abs(element.offsetTop - this.root.scrollTop) < Math.abs(best.offsetTop - this.root.scrollTop) ? element : best;
    }, null);
    const page = Number(closest?.dataset.comicContinuousPage);
    if (!Number.isFinite(page) || page === this.currentPage) return;
    this.currentPage = page;
    this.onCurrentPage(page);
  };
}

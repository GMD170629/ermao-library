interface HTMLElementTagNameMap {
  'foliate-view': HTMLElement;
}

declare module 'foliate-js/view.js' {
  export type FoliateNavigationTarget = string | number | { fraction: number };

  export interface FoliateBook {
    readonly metadata?: unknown;
    readonly toc?: readonly unknown[];
    readonly pageList?: readonly unknown[];
    readonly sections?: readonly unknown[];
    readonly rendition?: unknown;
    readonly dir?: string;
    destroy?: () => void | Promise<void>;
  }

  export class ResponseError extends Error {}
  export class NotFoundError extends Error {}
  export class UnsupportedTypeError extends Error {}

  export function makeBook(file: File | Blob | string): Promise<FoliateBook>;

  export class View extends HTMLElement {
    book?: FoliateBook;
    renderer?: unknown;
    lastLocation?: unknown;
    isFixedLayout: boolean;

    open(book: FoliateBook | File | Blob | string): Promise<void>;
    close(): void;
    init(options: { lastLocation?: unknown; showTextStart?: boolean }): Promise<void>;
    goTo(target: FoliateNavigationTarget): Promise<unknown>;
    goToFraction(fraction: number): Promise<unknown>;
    prev(distance?: number): Promise<unknown>;
    next(distance?: number): Promise<unknown>;
    goLeft(): unknown;
    goRight(): unknown;
  }
}

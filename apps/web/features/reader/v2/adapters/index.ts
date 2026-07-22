import { createComicAdapter } from './comic-adapter';
import { createEpubAdapter } from './epub-adapter';
import { createPdfAdapter } from './pdf-adapter';

export { createComicAdapter, ComicReaderAdapter } from './comic-adapter';
export type { ComicAdapterOptions, ComicPageView, ComicViewModel } from './comic-adapter';
export type { ComicPageMeta } from './comic-model';

export { createEpubAdapter, EpubReaderAdapter } from './epub-adapter';
export type { EpubAdapterNavigationItem, EpubAdapterOptions, EpubInputIntent } from './epub-adapter';

export { createPdfAdapter, PdfReaderAdapter } from './pdf-adapter';
export type { PdfAdapterOptions, PdfViewModel } from './pdf-adapter';

export { isReaderInteractiveAdapter } from './reader-interaction';
export type {
  ReaderAdapterInputHandler,
  ReaderAdapterInputIntent,
  ReaderInteractionPolicy,
  ReaderInteractiveAdapter
} from './reader-interaction';

export type ReaderAdapterFactoryOptions =
  | ({ kind: 'epub' } & import('./epub-adapter').EpubAdapterOptions)
  | ({ kind: 'comic' } & import('./comic-adapter').ComicAdapterOptions)
  | ({ kind: 'pdf' } & import('./pdf-adapter').PdfAdapterOptions);

export function createReaderAdapter(options: ReaderAdapterFactoryOptions) {
  if (options.kind === 'epub') return createEpubAdapter(options);
  if (options.kind === 'comic') return createComicAdapter(options);
  return createPdfAdapter(options);
}

import type { BookView } from '../../../types/book';

export function kindleSendOptions(book: Pick<BookView, 'resources'>) {
  return book.resources.flatMap((resource) => resource.assets
    .filter((asset) => resource.kindleSendAvailable && ['EPUB', 'PDF'].includes(resource.format) && asset.role === 'PRIMARY')
    .map((asset) => ({ assetId: asset.id, resourceId: resource.id, resourceTitle: resource.title,
      format: resource.format, size: asset.size })));
}

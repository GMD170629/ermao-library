import type { BookView } from '../../../types/book';

export function bookDownloadVolumes(book: Pick<BookView, 'resources'>) {
  return book.resources.filter((resource) => !resource.hidden).map((resource) => ({
    id: resource.id,
    title: resource.title,
    format: resource.format,
    assets: resource.assets.filter((asset) => asset.downloadUrl.trim().length > 0)
  }));
}

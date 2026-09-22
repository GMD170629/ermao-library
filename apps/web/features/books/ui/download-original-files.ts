import type { ResourceAssetView } from '../../../types/book';

/** Hand original URLs to the browser without buffering file contents in JavaScript. */
export function downloadOriginalFiles(assets: readonly ResourceAssetView[]): void {
  for (const asset of assets) {
    const link = document.createElement('a');
    link.href = asset.downloadUrl;
    link.download = '';
    link.target = '_blank';
    link.rel = 'noopener';
    document.body.append(link);
    link.click();
    link.remove();
  }
}

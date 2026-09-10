export function smallResourceCoverUrl(coverUrl: string): string {
  if (!coverUrl) return '';
  const sourceUrl = coverUrl;
  const fragmentIndex = sourceUrl.indexOf('#');
  const urlWithoutFragment = fragmentIndex >= 0 ? sourceUrl.slice(0, fragmentIndex) : sourceUrl;
  const fragment = fragmentIndex >= 0 ? sourceUrl.slice(fragmentIndex) : '';

  if (/(?:^|[?&])size=[^&#]*/.test(urlWithoutFragment)) {
    return `${urlWithoutFragment.replace(/([?&])size=[^&#]*/, '$1size=small')}${fragment}`;
  }

  const separator = urlWithoutFragment.includes('?') ? '&' : '?';
  return `${urlWithoutFragment}${separator}size=small${fragment}`;
}

export function smallResourceCoverUrl(resourceId: string, coverUrl: string): string {
  const sourceUrl = coverUrl || `/api/resources/${encodeURIComponent(resourceId)}/cover`;
  const fragmentIndex = sourceUrl.indexOf('#');
  const urlWithoutFragment = fragmentIndex >= 0 ? sourceUrl.slice(0, fragmentIndex) : sourceUrl;
  const fragment = fragmentIndex >= 0 ? sourceUrl.slice(fragmentIndex) : '';

  if (/(?:^|[?&])size=[^&#]*/.test(urlWithoutFragment)) {
    return `${urlWithoutFragment.replace(/([?&])size=[^&#]*/, '$1size=small')}${fragment}`;
  }

  const separator = urlWithoutFragment.includes('?') ? '&' : '?';
  return `${urlWithoutFragment}${separator}size=small${fragment}`;
}

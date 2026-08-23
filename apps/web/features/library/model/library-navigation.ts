export function libraryReturnHref(searchParameters: string): string {
  const parameters = new URLSearchParams(searchParameters);
  parameters.delete('upload');
  const query = parameters.toString();
  return query ? `/library?${query}` : '/library';
}

export function bookDetailHrefFromLibrary(bookId: string, searchParameters: string): string {
  const parameters = new URLSearchParams({
    returnTo: libraryReturnHref(searchParameters)
  });
  return `/books/${encodeURIComponent(bookId)}?${parameters}`;
}

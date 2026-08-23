export type LibraryNavigationSource = Readonly<{
  id: string;
  name: string;
}>;

export function librarySourceHref(source: LibraryNavigationSource): string {
  const filters = JSON.stringify({
    combinator: 'ALL',
    conditions: [{ field: 'library', operator: 'equals', value: source.id }]
  });
  const parameters = new URLSearchParams({ filters, libraryName: source.name });
  return `/library?${parameters.toString()}`;
}

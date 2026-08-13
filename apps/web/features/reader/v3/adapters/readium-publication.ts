import { HttpFetcher, Link, Manifest, Publication, type Locator } from '@readium/shared';

export type ReadiumPublication = Readonly<{
  publication: Publication;
  positions: Locator[];
}>;

/** Opens an authenticated RWPM. Private publication bytes stay in Reader-owned storage/server routes. */
export async function openReadiumPublication(manifestUrl: string): Promise<ReadiumPublication> {
  const absoluteUrl = new URL(manifestUrl, window.location.href).href;
  const fetcher = new HttpFetcher(undefined, absoluteUrl);
  const json: unknown = await fetcher.get(new Link({ href: absoluteUrl })).readAsJSON();
  const manifest = Manifest.deserialize(json);
  if (!manifest) throw new Error('READIUM_MANIFEST_INVALID');
  manifest.setSelfLink(absoluteUrl);
  const publication = new Publication({ manifest, fetcher: new HttpFetcher(undefined, absoluteUrl) });
  const positions = await publication.positionsFromManifest();
  if (positions.length === 0) throw new Error('READIUM_POSITIONS_MISSING');
  return { publication, positions };
}

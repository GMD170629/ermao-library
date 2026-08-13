import { HttpFetcher, Link, Manifest, Publication } from '@readium/shared';

export type PublicationCatalogEntry = Readonly<{ id: string }>;
export type PublicationFingerprint = Readonly<{
  originalFileHash: string;
  parser: string;
  normalization: string;
}>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export async function fetchPublicationCatalog(signal?: AbortSignal): Promise<PublicationCatalogEntry[]> {
  const response = await fetch('/publication-api/books', { signal });
  if (!response.ok) throw new Error(`catalog_http_${response.status}`);
  const body: unknown = await response.json();
  if (!isRecord(body) || !Array.isArray(body.books)) throw new Error('catalog_invalid');
  return body.books.map((entry) => {
    if (!isRecord(entry) || typeof entry.id !== 'string' || entry.id.length === 0) {
      throw new Error('catalog_entry_invalid');
    }
    return { id: entry.id };
  });
}

export type OpenPublicationResult = Readonly<{
  publication: Publication;
  positions: Awaited<ReturnType<Publication['positionsFromManifest']>>;
  manifestJson: unknown;
  manifestUrl: string;
  fingerprint?: PublicationFingerprint;
}>;

function publicationFingerprint(manifestJson: unknown): PublicationFingerprint | undefined {
  if (!isRecord(manifestJson)) return undefined;
  const runtime = manifestJson['https://shuku.app/reader/runtime'];
  if (!isRecord(runtime)
    || typeof runtime.originalFileHash !== 'string'
    || typeof runtime.parser !== 'string'
    || typeof runtime.normalization !== 'string') return undefined;
  return {
    originalFileHash: runtime.originalFileHash,
    parser: runtime.parser,
    normalization: runtime.normalization
  };
}

export async function openPublication(id: string): Promise<OpenPublicationResult> {
  const manifestUrl = new URL(
    `/publication-api/publications/${encodeURIComponent(id)}/manifest.json`,
    window.location.href
  ).href;
  const bootstrapFetcher = new HttpFetcher(undefined, manifestUrl);
  const manifestJson: unknown = await bootstrapFetcher.get(new Link({ href: manifestUrl })).readAsJSON();
  const manifest = Manifest.deserialize(manifestJson);
  if (!manifest) throw new Error('manifest_invalid');
  manifest.setSelfLink(manifestUrl);
  const publication = new Publication({
    manifest,
    fetcher: new HttpFetcher(undefined, manifestUrl)
  });
  const positions = await publication.positionsFromManifest();
  if (positions.length === 0) throw new Error('positions_missing');
  return { publication, positions, manifestJson, manifestUrl, fingerprint: publicationFingerprint(manifestJson) };
}

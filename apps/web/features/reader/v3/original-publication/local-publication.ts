import {
  Link,
  Locator,
  LocatorLocations,
  Manifest,
  NumberRange,
  Publication,
  Resource,
  type Fetcher
} from '@readium/shared';

const POSITION_CHARS = 1_024;

export type ReadiumPublication = Readonly<{
  publication: Publication;
  positions: Locator[];
  close: () => void;
}>;

class ByteResource extends Resource {
  constructor(
    private readonly publicationLink: Link,
    private readonly bytes: () => Promise<Uint8Array>,
    private readonly declaredLength?: number
  ) {
    super();
  }

  async link() { return this.publicationLink; }
  async length() {
    return Number.isSafeInteger(this.declaredLength) && (this.declaredLength ?? -1) >= 0
      ? this.declaredLength as number
      : (await this.bytes()).byteLength;
  }
  async read(range?: NumberRange) {
    const bytes = await this.bytes();
    return range
      ? bytes.slice(range.start, Math.min(bytes.byteLength, range.endInclusive + 1))
      : bytes;
  }
  close() {}
}

class LocalPublicationFetcher implements Fetcher {
  constructor(
    private readonly resources: ReadonlyMap<string, Readonly<{
      link: Link;
      size?: number;
      read: () => Promise<Uint8Array>;
    }>>,
    private readonly dispose: () => void
  ) {}

  links() { return [...this.resources.values()].map((resource) => resource.link); }

  get(link: Link): Resource {
    const href = link.href.split('#', 1)[0]?.split('?', 1)[0] ?? link.href;
    const resource = this.resources.get(href);
    return resource
      ? new ByteResource(resource.link, resource.read, resource.size)
      : new ByteResource(link, async () => { throw new Error('PUBLICATION_RESOURCE_NOT_FOUND'); });
  }

  close() { this.dispose(); }
}

function positionsFor(
  chapters: readonly Readonly<{ href: string; type: string; title: string; positionLength: number }>[]
): Locator[] {
  const weights = chapters.map((chapter) => Math.max(1, Math.ceil(chapter.positionLength / POSITION_CHARS)));
  const total = weights.reduce((sum, value) => sum + value, 0);
  let absolute = 0;
  return chapters.flatMap((chapter, chapterIndex) => Array.from(
    { length: weights[chapterIndex] ?? 1 },
    (_, resourceIndex) => {
      const position = ++absolute;
      return new Locator({
        href: chapter.href,
        type: chapter.type,
        title: chapter.title,
        locations: new LocatorLocations({
          progression: resourceIndex / (weights[chapterIndex] ?? 1),
          totalProgression: total <= 1 ? 0 : (position - 1) / (total - 1),
          position
        })
      });
    }
  ));
}

export function createLocalPublication(input: Readonly<{
  title: string;
  language?: string | null;
  readingOrder: readonly Readonly<{
    href: string;
    type: string;
    title: string;
    size?: number;
    positionLength: number;
    read: () => Promise<Uint8Array>;
  }>[];
  toc?: readonly Readonly<{ href: string; title: string }>[];
  extraResources?: readonly Readonly<{
    href: string;
    type: string;
    size?: number;
    read: () => Promise<Uint8Array>;
  }>[];
  onClose?: () => void;
}>): ReadiumPublication {
  const readingOrder = input.readingOrder.map((item) => ({
    href: item.href,
    type: item.type,
    title: item.title
  }));
  const manifest = Manifest.deserialize({
    metadata: { title: input.title, ...(input.language ? { language: input.language } : {}) },
    readingOrder,
    resources: (input.extraResources ?? []).map((item) => ({ href: item.href, type: item.type })),
    toc: (input.toc ?? readingOrder).map((item) => ({
      href: item.href,
      title: item.title,
      type: 'application/xhtml+xml'
    }))
  });
  if (!manifest || readingOrder.length === 0) throw new Error('PUBLICATION_STRUCTURE_INVALID');

  const entries = new Map<string, Readonly<{
    link: Link;
    size?: number;
    read: () => Promise<Uint8Array>;
  }>>();
  for (const item of input.readingOrder) {
    entries.set(item.href, {
      link: new Link({
        href: item.href,
        type: item.type,
        title: item.title,
        size: item.size
      }),
      ...(item.size === undefined ? {} : { size: item.size }),
      read: item.read
    });
  }
  for (const item of input.extraResources ?? []) {
    entries.set(item.href, {
      link: new Link({ href: item.href, type: item.type, size: item.size }),
      ...(item.size === undefined ? {} : { size: item.size }),
      read: item.read
    });
  }

  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    input.onClose?.();
  };
  const publication = new Publication({
    manifest,
    fetcher: new LocalPublicationFetcher(entries, close)
  });
  return { publication, positions: positionsFor(input.readingOrder), close };
}

import {
  OriginalPublicationStoreError,
  ORIGINAL_CHUNK_BYTES,
  type OriginalArtifact,
  type OriginalPublicationDescriptor,
  type OriginalStoragePort,
  type OriginalStoreSession
} from './original-store-contract';

export const ORIGINAL_DATABASE_NAME = 'shuku-reader-originals-v1';

const METADATA = 'metadata';
const CHUNKS = 'chunks';
const SESSION_KEY = 'session';

type ArtifactRecord = {
  key: string;
  namespace: string;
  epoch: string;
  identity: string;
  resource: string;
  mime: string;
  size: number;
  length: number;
  count: number;
  complete: boolean;
};

function identity(descriptor: OriginalPublicationDescriptor): string {
  return JSON.stringify([descriptor.namespace, descriptor.resourceId, descriptor.assetId,
    descriptor.assetVersion, descriptor.sourceFormat, descriptor.mimeType, descriptor.sizeBytes]);
}
function resource(descriptor: OriginalPublicationDescriptor): string {
  return JSON.stringify([descriptor.namespace, descriptor.resourceId, descriptor.assetId]);
}
function object(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null) throw new OriginalPublicationStoreError('ORIGINAL_CACHE_IO');
  return value as Record<string, unknown>;
}
function artifactRecord(value: unknown): ArtifactRecord {
  const item = object(value);
  if (typeof item.key !== 'string' || !item.key.startsWith('artifact:')
    || typeof item.namespace !== 'string' || typeof item.epoch !== 'string'
    || typeof item.identity !== 'string' || typeof item.resource !== 'string'
    || typeof item.mime !== 'string' || typeof item.complete !== 'boolean'
    || typeof item.size !== 'number' || !Number.isSafeInteger(item.size) || item.size < 0
    || typeof item.length !== 'number' || !Number.isSafeInteger(item.length) || item.length < 0 || item.length > item.size
    || typeof item.count !== 'number' || !Number.isSafeInteger(item.count) || item.count < 0 || item.count > item.length) {
    throw new OriginalPublicationStoreError('ORIGINAL_CACHE_IO');
  }
  return { key: item.key, namespace: item.namespace, epoch: item.epoch, identity: item.identity,
    resource: item.resource, mime: item.mime, complete: item.complete, size: item.size,
    length: item.length, count: item.count };
}
function uniqueId(): string {
  return [...crypto.getRandomValues(new Uint32Array(4))].map((part) => part.toString(16).padStart(8, '0')).join('');
}
function request<T>(operation: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    operation.onsuccess = () => resolve(operation.result);
    operation.onerror = () => reject(operation.error ?? new OriginalPublicationStoreError('ORIGINAL_CACHE_IO'));
  });
}
function aborted(): DOMException { return new DOMException('Reader session changed', 'AbortError'); }

/** One database for original bytes. Every write checks the session in the same transaction. */
export class IndexedDbPublicationStorage implements OriginalStoragePort {
  private database: Promise<IDBDatabase> | null = null;
  private transition: Promise<void> = Promise.resolve();
  private requestedNamespace: string | null = null;

  constructor(private readonly factory: () => IDBFactory = () => indexedDB) {}

  private open(): Promise<IDBDatabase> {
    if (this.database) return this.database;
    const opening = new Promise<IDBDatabase>((resolve, reject) => {
      const operation = this.factory().open(ORIGINAL_DATABASE_NAME, 1);
      let blocked = false;
      operation.onupgradeneeded = () => {
        const db = operation.result;
        const metadata = db.createObjectStore(METADATA, { keyPath: 'key' });
        metadata.createIndex('identity', 'identity');
        metadata.createIndex('namespace', 'namespace');
        db.createObjectStore(CHUNKS, { keyPath: ['artifact', 'index'] });
      };
      operation.onsuccess = () => {
        const db = operation.result;
        if (blocked) { db.close(); return; }
        db.onversionchange = () => { db.close(); this.database = null; };
        db.onclose = () => { this.database = null; };
        resolve(db);
      };
      operation.onerror = () => reject(operation.error ?? new OriginalPublicationStoreError('ORIGINAL_CACHE_IO'));
      operation.onblocked = () => { blocked = true; reject(new OriginalPublicationStoreError('ORIGINAL_CACHE_IO')); };
    });
    this.database = opening;
    void opening.catch(() => { if (this.database === opening) this.database = null; });
    return opening;
  }

  private async transaction<T>(mode: IDBTransactionMode, action: (tx: IDBTransaction) => Promise<T>, signal?: AbortSignal): Promise<T> {
    const db = await this.open();
    signal?.throwIfAborted();
    const tx = db.transaction([METADATA, CHUNKS], mode);
    const cancel = () => { try { tx.abort(); } catch { /* transaction already committed */ } };
    signal?.addEventListener('abort', cancel, { once: true });
    const completed = new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onabort = () => reject(tx.error ?? aborted());
      tx.onerror = () => { /* onabort owns transaction failure */ };
    });
    // Observe early aborts while a request is still settling.
    void completed.catch(() => undefined);
    try {
      const result = await action(tx);
      await completed;
      return result;
    } catch (error) {
      try { tx.abort(); } catch { /* already settled */ }
      await completed.catch(() => undefined);
      throw error;
    } finally { signal?.removeEventListener('abort', cancel); }
  }

  private async authorize(tx: IDBTransaction, session: OriginalStoreSession): Promise<void> {
    const value: unknown = await request(tx.objectStore(METADATA).get(SESSION_KEY));
    if (!value) throw aborted();
    const stored = object(value);
    if (stored.namespace !== session.namespace || stored.epoch !== session.epoch) throw aborted();
  }

  /** Same-namespace activation preserves complete files and does not invalidate another tab. */
  activate(namespace: string | null): Promise<void> {
    this.requestedNamespace = namespace;
    const next = this.transition.catch(() => undefined).then(() => this.transaction('readwrite', async (tx) => {
      const metadata = tx.objectStore(METADATA);
      const value: unknown = await request(metadata.get(SESSION_KEY));
      if (namespace !== null && value && object(value).namespace === namespace) return;
      await request(metadata.clear());
      await request(tx.objectStore(CHUNKS).clear());
      await request(metadata.put({ key: SESSION_KEY, namespace, epoch: uniqueId() }));
    }));
    this.transition = next;
    return next;
  }

  async session(namespace: string): Promise<OriginalStoreSession> {
    await this.transition.catch((cause: unknown) => {
      // Retry a failed activation only while it is still the latest authorized intent.
      // A successful activation followed by another tab's logout must never be replayed.
      if (this.requestedNamespace !== namespace) throw cause;
      return this.activate(namespace);
    });
    return this.transaction('readonly', async (tx) => {
      const value: unknown = await request(tx.objectStore(METADATA).get(SESSION_KEY));
      if (!value) throw aborted();
      const item = object(value);
      if (item.namespace !== namespace || typeof item.epoch !== 'string') throw aborted();
      return { namespace, epoch: item.epoch };
    });
  }

  private async remove(tx: IDBTransaction, id: string): Promise<void> {
    await request(tx.objectStore(CHUNKS).delete(IDBKeyRange.bound([id, 0], [id, Number.MAX_SAFE_INTEGER])));
    await request(tx.objectStore(METADATA).delete(id));
  }

  async read(session: OriginalStoreSession, descriptor: OriginalPublicationDescriptor): Promise<Blob | null> {
    return this.transaction('readwrite', async (tx) => {
      await this.authorize(tx, session);
      const values: unknown[] = await request(tx.objectStore(METADATA).index('identity').getAll(identity(descriptor)));
      for (const value of values) {
        const item = object(value);
        if (typeof item.key !== 'string' || !item.key.startsWith('artifact:')) {
          throw new OriginalPublicationStoreError('ORIGINAL_CACHE_IO');
        }
        try {
          const record = artifactRecord(value);
          if (!record.complete || record.epoch !== session.epoch) continue;
          if (record.length !== descriptor.sizeBytes || record.size !== descriptor.sizeBytes
            || record.namespace !== session.namespace || record.resource !== resource(descriptor)
            || record.mime !== descriptor.mimeType) throw new OriginalPublicationStoreError('ORIGINAL_CACHE_IO');
          const parts: Blob[] = [];
          let length = 0;
          for (let index = 0; index < record.count; index += 1) {
            const chunk = object(await request(tx.objectStore(CHUNKS).get([record.key, index])));
            if (chunk.artifact !== record.key || chunk.index !== index || !(chunk.blob instanceof Blob)
              || chunk.blob.size === 0 || chunk.blob.size > ORIGINAL_CHUNK_BYTES) {
              throw new OriginalPublicationStoreError('ORIGINAL_CACHE_IO');
            }
            length += chunk.blob.size;
            if (length > record.size) throw new OriginalPublicationStoreError('ORIGINAL_CACHE_IO');
            parts.push(chunk.blob);
          }
          if (length !== record.size) throw new OriginalPublicationStoreError('ORIGINAL_CACHE_IO');
          return new Blob(parts, { type: record.mime });
        } catch (cause) {
          if (!(cause instanceof OriginalPublicationStoreError)) throw cause;
          // Invalid cached metadata/bytes are disposable; an actual IDB failure still propagates.
          await this.remove(tx, item.key);
        }
      }
      return null;
    });
  }

  async begin(session: OriginalStoreSession, descriptor: OriginalPublicationDescriptor): Promise<OriginalArtifact> {
    const id = `artifact:${uniqueId()}`;
    await this.transaction('readwrite', async (tx) => {
      await this.authorize(tx, session);
      await request(tx.objectStore(METADATA).put({ key: id, namespace: session.namespace, epoch: session.epoch,
        identity: identity(descriptor), resource: resource(descriptor), mime: descriptor.mimeType,
        size: descriptor.sizeBytes, length: 0, count: 0, complete: false } satisfies ArtifactRecord));
    });
    return { id, session };
  }

  async append(artifact: OriginalArtifact, chunk: Blob): Promise<void> {
    if (chunk.size <= 0 || chunk.size > ORIGINAL_CHUNK_BYTES) throw new OriginalPublicationStoreError('ORIGINAL_LENGTH_INVALID');
    await this.transaction('readwrite', async (tx) => {
      await this.authorize(tx, artifact.session);
      const metadata = tx.objectStore(METADATA);
      const record = artifactRecord(await request(metadata.get(artifact.id)));
      if (record.complete || record.epoch !== artifact.session.epoch) throw aborted();
      if (record.length + chunk.size > record.size) throw new OriginalPublicationStoreError('ORIGINAL_LENGTH_INVALID');
      await request(tx.objectStore(CHUNKS).put({ artifact: artifact.id, index: record.count, blob: chunk }));
      await request(metadata.put({ ...record, length: record.length + chunk.size, count: record.count + 1 }));
    });
  }

  async complete(artifact: OriginalArtifact, signal: AbortSignal): Promise<void> {
    await this.transaction('readwrite', async (tx) => {
      await this.authorize(tx, artifact.session);
      const metadata = tx.objectStore(METADATA);
      const record = artifactRecord(await request(metadata.get(artifact.id)));
      if (record.length !== record.size) throw new OriginalPublicationStoreError('ORIGINAL_LENGTH_INVALID');
      await request(metadata.put({ ...record, complete: true }));
      const values: unknown[] = await request(metadata.index('namespace').getAll(artifact.session.namespace));
      for (const value of values) {
        const item = object(value);
        if (item.key === SESSION_KEY) continue;
        const old = artifactRecord(value);
        if (old.key !== artifact.id && old.complete && old.resource === record.resource) await this.remove(tx, old.key);
      }
    }, signal);
  }

  async discard(artifact: OriginalArtifact): Promise<void> {
    await this.transaction('readwrite', (tx) => this.remove(tx, artifact.id));
  }

  async reclaim(session: OriginalStoreSession, descriptor: OriginalPublicationDescriptor): Promise<number> {
    return this.transaction('readwrite', async (tx) => {
      await this.authorize(tx, session);
      const values: unknown[] = await request(tx.objectStore(METADATA).index('namespace').getAll(session.namespace));
      let deleted = 0;
      for (const value of values) {
        if (object(value).key === SESSION_KEY) continue;
        const record = artifactRecord(value);
        if (record.complete && record.identity !== identity(descriptor)) {
          await this.remove(tx, record.key);
          deleted += 1;
        }
      }
      return deleted;
    });
  }
}

import { type ReaderKind, type ReaderLocation, type ReflowableFormat } from '@shuku/reader-core';
import {
  progressLocationsMatch,
  v4LocationToDomain,
  type ExactProgressRecord,
  type PendingProgressMutation,
  type PendingVsServerDecision,
  type ReaderProgressSnapshot
} from '../../../lib/reader';

export type LocalResumeContext = { readerKind: ReaderKind; sourceFormat?: ReflowableFormat };
export type StartupResumeDecision = { location: ReaderLocation | null; percent: number; source: 'direct-target' | 'local-exact' | 'server'; localExact: ExactProgressRecord | null };

export function decidePendingVsServer(input: {
  localExact: ExactProgressRecord | null;
  pending: PendingProgressMutation | null;
  serverSnapshot: ReaderProgressSnapshot | null;
  bookId: string;
  resourceId: string;
}): PendingVsServerDecision {
  const pending = input.pending;
  if (!pending) return { kind: 'server', snapshot: input.serverSnapshot, discardPendingMutationId: null };
  const validLocal = input.localExact
    && input.localExact.bookId === input.bookId
    && input.localExact.resourceId === input.resourceId
    && pending.bookId === input.bookId
    && pending.resourceId === input.resourceId
    && input.localExact.serverIdentity === pending.serverIdentity
    && input.localExact.userId === pending.userId
    && input.localExact.clientId === pending.clientId
    && input.localExact.bookId === pending.bookId
    && input.localExact.resourceId === pending.resourceId
    && progressLocationsMatch(input.localExact.locator, pending.locator)
    ? input.localExact : null;
  if (!validLocal) {
    return { kind: 'server', snapshot: input.serverSnapshot, discardPendingMutationId: pending.mutationId };
  }
  if (!input.serverSnapshot || pending.baseRevision === input.serverSnapshot.revision) {
    return { kind: 'local-pending', pending, localExact: validLocal, rebaseRevision: null };
  }
  if (input.serverSnapshot.revision > pending.baseRevision) {
    const serverCapturedAt = input.serverSnapshot.capturedAtEpochMillis ?? input.serverSnapshot.receivedAtEpochMillis;
    if (serverCapturedAt >= validLocal.capturedAtEpochMillis) {
      return { kind: 'server', snapshot: input.serverSnapshot, discardPendingMutationId: pending.mutationId };
    }
    return {
      kind: 'local-pending',
      pending,
      localExact: validLocal,
      rebaseRevision: input.serverSnapshot.revision
    };
  }
  return { kind: 'local-pending', pending, localExact: validLocal, rebaseRevision: null };
}

export function resolveStartupResume(input: {
  localExact: ExactProgressRecord | null;
  serverSnapshot: ReaderProgressSnapshot | null;
  context: LocalResumeContext;
  serverLocation: ReaderLocation | null;
  serverPercent: number;
  hasDirectTarget: boolean;
  bookId: string;
  resourceId: string;
}): StartupResumeDecision {
  if (input.hasDirectTarget) return { location: input.serverLocation, percent: input.serverPercent, source: 'direct-target', localExact: null };
  const validLocal = input.localExact?.bookId === input.bookId && input.localExact.resourceId === input.resourceId
    ? input.localExact : null;
  const localLocation = validLocal ? v4LocationToDomain(
    validLocal.locator,
    input.resourceId,
    input.context.readerKind === 'reflowable' ? input.context.sourceFormat ?? null : null
  ) : null;
  const serverCapturedAt = input.serverSnapshot
    ? input.serverSnapshot.capturedAtEpochMillis ?? input.serverSnapshot.receivedAtEpochMillis
    : null;
  if (validLocal && localLocation && (serverCapturedAt === null || validLocal.capturedAtEpochMillis > serverCapturedAt)) {
    return {
      location: localLocation,
      percent: validLocal.displayPercent ?? 0,
      source: 'local-exact',
      localExact: validLocal
    };
  }
  return { location: input.serverLocation, percent: input.serverPercent, source: 'server', localExact: null };
}

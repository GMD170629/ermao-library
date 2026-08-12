import type { ReaderKind, ReaderLocation, ReflowableFormat } from '@shuku/reader-core';
import type { ExactProgressRecord, ReaderProgressSnapshot } from '../../../lib/reader';

export type LocalResumeContext = {
  readerKind: ReaderKind;
  sourceFormat?: ReflowableFormat;
};

export type StartupResumeDecision = {
  location: ReaderLocation | null;
  percent: number;
  source: 'direct-target' | 'local-exact' | 'server';
  localExact: ExactProgressRecord | null;
};

function locationForContext(location: ExactProgressRecord['location'], context: LocalResumeContext): ReaderLocation | null {
  if (location.kind === 'audio') return null;
  if (context.readerKind === 'reflowable') {
    if (location.kind === 'epub') {
      return {
        kind: 'reflowable',
        format: 'epub',
        cfi: location.cfi,
        href: location.href,
        progression: location.progression
      };
    }
    if (location.kind !== 'reflowable') return null;
    return !context.sourceFormat || location.format === context.sourceFormat ? location : null;
  }
  return location.kind === context.readerKind ? location : null;
}

/** Explicit navigation wins; otherwise local exact wins timestamp ties. */
export function resolveStartupResume(input: {
  localExact: ExactProgressRecord | null;
  serverSnapshot: ReaderProgressSnapshot | null;
  context: LocalResumeContext;
  serverLocation: ReaderLocation | null;
  serverPercent: number;
  hasDirectTarget: boolean;
}): StartupResumeDecision {
  if (input.hasDirectTarget) {
    return {
      location: input.serverLocation,
      percent: input.serverPercent,
      source: 'direct-target',
      localExact: null
    };
  }

  const localLocation = input.localExact
    ? locationForContext(input.localExact.location, input.context)
    : null;
  const localWins = Boolean(
    input.localExact
    && localLocation
    && (
      !input.serverSnapshot
      || input.localExact.updatedAtEpochMillis >= input.serverSnapshot.updatedAtEpochMillis
    )
  );
  if (localWins && input.localExact && localLocation) {
    const approximatePercent = localLocation.kind === 'reflowable' && typeof localLocation.progression === 'number'
      ? localLocation.progression * 100
      : input.serverPercent;
    return {
      location: localLocation,
      percent: input.localExact.percent ?? approximatePercent,
      source: 'local-exact',
      localExact: input.localExact
    };
  }

  return {
    location: input.serverLocation,
    percent: input.serverPercent,
    source: 'server',
    localExact: null
  };
}

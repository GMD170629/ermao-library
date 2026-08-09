import type { ServerBaseUrl } from './server-address';

const SAFE_PROFILE_ID = /^[A-Za-z0-9-]{1,128}$/;
export const MAXIMUM_SERVER_PROFILES = 100;

export type ServerProfile = Readonly<{
  id: string;
  baseUrl: ServerBaseUrl;
  service: 'ermao-books';
  initialized: boolean;
  createdAtMs: number;
  lastVerifiedAtMs: number;
}>;

export type ServerProfilesDocument = Readonly<{
  format: 'shuku.server-profiles';
  schemaVersion: 2;
  generation: number;
  activeProfileId: string | null;
  profiles: readonly ServerProfile[];
  updatedAtMs: number;
}>;

export type ServerProfileCatalog = Readonly<{
  generation: number;
  activeProfileId: string | null;
  profiles: readonly ServerProfile[];
  updatedAtMs: number;
}>;

export type ActivateServerProfileCommand = Readonly<{
  baseUrl: ServerBaseUrl;
  initialized: boolean;
  proposedProfileId: string;
  verifiedAtMs: number;
}>;

export type ActivateServerProfileResult = Readonly<{
  document: ServerProfilesDocument;
  profile: ServerProfile;
}>;

export type ActivateExistingServerProfileCommand = Readonly<{
  profileId: string;
  expectedBaseUrl: string;
  initialized: boolean;
  verifiedAtMs: number;
}>;

export type DeleteServerProfileCommand = Readonly<{
  profileId: string;
  deletedAtMs: number;
}>;

export type ServerProfileInvariantErrorCode =
  | 'CAPACITY_REACHED'
  | 'INVALID_COMMAND'
  | 'PROFILE_CHANGED'
  | 'PROFILE_ID_CONFLICT'
  | 'PROFILE_NOT_FOUND';

export class ServerProfileInvariantError extends Error {
  constructor(
    readonly code: ServerProfileInvariantErrorCode,
    message: string,
  ) {
    super(message);
    this.name = 'ServerProfileInvariantError';
  }
}

export function isSafeProfileId(value: string): boolean {
  return SAFE_PROFILE_ID.test(value);
}

export function serverProfileCatalog(
  document: ServerProfilesDocument | null,
): ServerProfileCatalog {
  return document === null
    ? {
        generation: 0,
        activeProfileId: null,
        profiles: [],
        updatedAtMs: 0,
      }
    : {
        generation: document.generation,
        activeProfileId: document.activeProfileId,
        profiles: document.profiles,
        updatedAtMs: document.updatedAtMs,
      };
}

export function activateServerProfile(
  current: ServerProfilesDocument | null,
  command: ActivateServerProfileCommand,
): ActivateServerProfileResult {
  if (
    !isSafeProfileId(command.proposedProfileId) ||
    !Number.isSafeInteger(command.verifiedAtMs) ||
    command.verifiedAtMs < 0
  ) {
    throw new ServerProfileInvariantError(
      'INVALID_COMMAND',
      'Server profile command contains invalid identity or time data',
    );
  }

  const existing = current?.profiles.find(
    (profile) => profile.baseUrl.value === command.baseUrl.value,
  );
  if (
    existing === undefined &&
    current?.profiles.some(
      (profile) => profile.id === command.proposedProfileId,
    )
  ) {
    throw new ServerProfileInvariantError(
      'PROFILE_ID_CONFLICT',
      'Generated server profile identifier is already in use',
    );
  }
  if (
    existing === undefined &&
    (current?.profiles.length ?? 0) >= MAXIMUM_SERVER_PROFILES
  ) {
    throw new ServerProfileInvariantError(
      'CAPACITY_REACHED',
      'Server profile capacity has been reached',
    );
  }

  const effectiveVerifiedAtMs = Math.max(
    command.verifiedAtMs,
    current?.updatedAtMs ?? 0,
  );
  const profile: ServerProfile =
    existing === undefined
      ? {
          id: command.proposedProfileId,
          baseUrl: command.baseUrl,
          service: 'ermao-books',
          initialized: command.initialized,
          createdAtMs: effectiveVerifiedAtMs,
          lastVerifiedAtMs: effectiveVerifiedAtMs,
        }
      : {
          ...existing,
          baseUrl: command.baseUrl,
          initialized: command.initialized,
          lastVerifiedAtMs: effectiveVerifiedAtMs,
        };
  const profiles =
    existing === undefined
      ? [...(current?.profiles ?? []), profile]
      : (current?.profiles ?? []).map((candidate) =>
          candidate.id === existing.id ? profile : candidate,
        );

  return {
    profile,
    document: {
      format: 'shuku.server-profiles',
      schemaVersion: 2,
      generation: (current?.generation ?? 0) + 1,
      activeProfileId: profile.id,
      profiles,
      updatedAtMs: effectiveVerifiedAtMs,
    },
  };
}

export function activateExistingServerProfile(
  current: ServerProfilesDocument | null,
  command: ActivateExistingServerProfileCommand,
): ActivateServerProfileResult {
  if (
    !isSafeProfileId(command.profileId) ||
    !Number.isSafeInteger(command.verifiedAtMs) ||
    command.verifiedAtMs < 0
  ) {
    throw new ServerProfileInvariantError(
      'INVALID_COMMAND',
      'Existing server profile command contains invalid identity or time data',
    );
  }
  const existing = current?.profiles.find(
    (profile) => profile.id === command.profileId,
  );
  if (current === null || existing === undefined) {
    throw new ServerProfileInvariantError(
      'PROFILE_NOT_FOUND',
      'Server profile no longer exists',
    );
  }
  if (existing.baseUrl.value !== command.expectedBaseUrl) {
    throw new ServerProfileInvariantError(
      'PROFILE_CHANGED',
      'Server profile changed while it was being verified',
    );
  }

  const effectiveVerifiedAtMs = Math.max(
    command.verifiedAtMs,
    current.updatedAtMs,
  );
  const profile: ServerProfile = {
    ...existing,
    initialized: command.initialized,
    lastVerifiedAtMs: effectiveVerifiedAtMs,
  };
  return {
    profile,
    document: {
      ...current,
      generation: current.generation + 1,
      activeProfileId: profile.id,
      profiles: current.profiles.map((candidate) =>
        candidate.id === profile.id ? profile : candidate,
      ),
      updatedAtMs: effectiveVerifiedAtMs,
    },
  };
}

export function deleteServerProfile(
  current: ServerProfilesDocument | null,
  command: DeleteServerProfileCommand,
): ServerProfilesDocument {
  if (
    !isSafeProfileId(command.profileId) ||
    !Number.isSafeInteger(command.deletedAtMs) ||
    command.deletedAtMs < 0
  ) {
    throw new ServerProfileInvariantError(
      'INVALID_COMMAND',
      'Delete server profile command contains invalid identity or time data',
    );
  }
  if (
    current === null ||
    !current.profiles.some((profile) => profile.id === command.profileId)
  ) {
    throw new ServerProfileInvariantError(
      'PROFILE_NOT_FOUND',
      'Server profile no longer exists',
    );
  }

  const effectiveDeletedAtMs = Math.max(
    command.deletedAtMs,
    current.updatedAtMs,
  );
  return {
    ...current,
    generation: current.generation + 1,
    activeProfileId:
      current.activeProfileId === command.profileId
        ? null
        : current.activeProfileId,
    profiles: current.profiles.filter(
      (profile) => profile.id !== command.profileId,
    ),
    updatedAtMs: effectiveDeletedAtMs,
  };
}

import type { ServerBaseUrl } from './server-address';

const SAFE_PROFILE_ID = /^[A-Za-z0-9-]{1,128}$/;
export const MAXIMUM_SERVER_PROFILES = 100;

export type ServerProfile = Readonly<{
  id: string;
  baseUrl: ServerBaseUrl;
  service: 'ermao-books';
  createdAtMs: number;
  lastVerifiedAtMs: number;
}>;

export type ServerProfilesDocumentV1 = Readonly<{
  format: 'shuku.server-profiles';
  schemaVersion: 1;
  generation: number;
  activeProfileId: string | null;
  profiles: readonly ServerProfile[];
  updatedAtMs: number;
}>;

export type ActivateServerProfileCommand = Readonly<{
  baseUrl: ServerBaseUrl;
  proposedProfileId: string;
  verifiedAtMs: number;
}>;

export type ActivateServerProfileResult = Readonly<{
  document: ServerProfilesDocumentV1;
  profile: ServerProfile;
}>;

export type ServerProfileInvariantErrorCode =
  | 'CAPACITY_REACHED'
  | 'INVALID_COMMAND'
  | 'PROFILE_ID_CONFLICT';

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

export function activateServerProfile(
  current: ServerProfilesDocumentV1 | null,
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
          createdAtMs: effectiveVerifiedAtMs,
          lastVerifiedAtMs: effectiveVerifiedAtMs,
        }
      : {
          ...existing,
          baseUrl: command.baseUrl,
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
      schemaVersion: 1,
      generation: (current?.generation ?? 0) + 1,
      activeProfileId: profile.id,
      profiles,
      updatedAtMs: effectiveVerifiedAtMs,
    },
  };
}

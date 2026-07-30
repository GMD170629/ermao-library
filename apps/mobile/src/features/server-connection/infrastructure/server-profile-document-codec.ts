import type { JsonDocumentCodec } from '../../../shared/files/snapshot-document-store';
import {
  type ValidationResult,
  hasOnlyKeys,
  isRecord,
  nonEmptyString,
  nonNegativeSafeInteger,
} from '../../../shared/validation/unknown';
import {
  isSafeProfileId,
  MAXIMUM_SERVER_PROFILES,
  type ServerProfile,
  type ServerProfilesDocumentV1,
} from '../model/server-profile';
import { parseServerAddress } from '../model/server-address';

const DOCUMENT_KEYS = new Set([
  'format',
  'schemaVersion',
  'generation',
  'activeProfileId',
  'profiles',
  'updatedAtMs',
]);
const PROFILE_KEYS = new Set([
  'id',
  'baseUrl',
  'service',
  'createdAtMs',
  'lastVerifiedAtMs',
]);
function decodeProfile(value: unknown): ServerProfile | null {
  if (!isRecord(value) || !hasOnlyKeys(value, PROFILE_KEYS)) {
    return null;
  }

  const id = nonEmptyString(value.id, 128);
  const baseUrlText = nonEmptyString(value.baseUrl, 2_048);
  const createdAtMs = nonNegativeSafeInteger(value.createdAtMs);
  const lastVerifiedAtMs = nonNegativeSafeInteger(value.lastVerifiedAtMs);
  if (
    id === null ||
    !isSafeProfileId(id) ||
    baseUrlText === null ||
    value.service !== 'ermao-books' ||
    createdAtMs === null ||
    lastVerifiedAtMs === null ||
    lastVerifiedAtMs < createdAtMs
  ) {
    return null;
  }

  const parsedAddress = parseServerAddress(baseUrlText);
  if (
    !parsedAddress.ok ||
    parsedAddress.baseUrl.value !== baseUrlText
  ) {
    return null;
  }

  return {
    id,
    baseUrl: parsedAddress.baseUrl,
    service: 'ermao-books',
    createdAtMs,
    lastVerifiedAtMs,
  };
}

export const serverProfilesDocumentCodec: JsonDocumentCodec<ServerProfilesDocumentV1> =
  {
    decode(value: unknown): ValidationResult<ServerProfilesDocumentV1> {
      if (
        !isRecord(value) ||
        !hasOnlyKeys(value, DOCUMENT_KEYS) ||
        value.format !== 'shuku.server-profiles' ||
        value.schemaVersion !== 1 ||
        !Array.isArray(value.profiles) ||
        value.profiles.length > MAXIMUM_SERVER_PROFILES
      ) {
        return { ok: false, reason: 'INVALID_SERVER_PROFILES_DOCUMENT' };
      }

      const generation = nonNegativeSafeInteger(value.generation);
      const updatedAtMs = nonNegativeSafeInteger(value.updatedAtMs);
      const activeProfileId =
        value.activeProfileId === null
          ? null
          : nonEmptyString(value.activeProfileId, 128);
      const profiles = value.profiles.map(decodeProfile);
      if (
        generation === null ||
        generation < 1 ||
        updatedAtMs === null ||
        (value.activeProfileId !== null &&
          (activeProfileId === null ||
            !isSafeProfileId(activeProfileId))) ||
        profiles.some((profile) => profile === null)
      ) {
        return { ok: false, reason: 'INVALID_SERVER_PROFILES_DOCUMENT' };
      }

      const validProfiles = profiles.filter(
        (profile): profile is ServerProfile => profile !== null,
      );
      const profileIds = new Set(validProfiles.map((profile) => profile.id));
      const baseUrls = new Set(
        validProfiles.map((profile) => profile.baseUrl.value),
      );
      if (
        profileIds.size !== validProfiles.length ||
        baseUrls.size !== validProfiles.length ||
        (activeProfileId !== null && !profileIds.has(activeProfileId)) ||
        validProfiles.some(
          (profile) => profile.lastVerifiedAtMs > updatedAtMs,
        )
      ) {
        return { ok: false, reason: 'INVALID_SERVER_PROFILES_DOCUMENT' };
      }

      return {
        ok: true,
        value: {
          format: 'shuku.server-profiles',
          schemaVersion: 1,
          generation,
          activeProfileId,
          profiles: validProfiles,
          updatedAtMs,
        },
      };
    },

    encode(document: ServerProfilesDocumentV1): unknown {
      return {
        format: document.format,
        schemaVersion: document.schemaVersion,
        generation: document.generation,
        activeProfileId: document.activeProfileId,
        profiles: document.profiles.map((profile) => ({
          id: profile.id,
          baseUrl: profile.baseUrl.value,
          service: profile.service,
          createdAtMs: profile.createdAtMs,
          lastVerifiedAtMs: profile.lastVerifiedAtMs,
        })),
        updatedAtMs: document.updatedAtMs,
      };
    },
  };

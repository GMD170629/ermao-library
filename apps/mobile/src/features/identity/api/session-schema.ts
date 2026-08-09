import {
  type ValidationResult,
  finiteNumberInRange,
  hasOnlyKeys,
  isRecord,
  nonEmptyString,
  nonNegativeSafeInteger,
} from '../../../shared/validation/unknown';
import type {
  AuthenticatedSession,
  AuthenticatedUser,
  AuthorizationSnapshot,
  SupportedLocale,
  UserPreferences,
} from '../model/session';

const ENVELOPE_KEYS = new Set(['ok', 'data']);
const SESSION_KEYS = new Set(['user', 'authorization', 'preferences']);
const USER_KEYS = new Set([
  'id',
  'email',
  'name',
  'role',
  'status',
  'canManageSystem',
  'canViewManualImports',
  'authzVersion',
  'avatarUrl',
  'locale',
]);
const AUTHORIZATION_KEYS = new Set([
  'isAdmin',
  'canManageSystem',
  'allLibraryScopes',
  'monitorFolderIds',
  'canViewManualImports',
  'authzVersion',
]);
const PREFERENCE_KEYS = new Set([
  'locale',
  'library.view',
  'library.sort',
  'library.sortDirection',
  'audio.playbackRate',
  'kindle.email',
]);
const SETUP_KEYS = new Set(['initialized']);
const LOGOUT_KEYS = new Set(['loggedOut']);

function locale(value: unknown): SupportedLocale | null {
  return value === 'zh-CN' || value === 'en-US' ? value : null;
}

function monitorFolderIds(value: unknown): string[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const folders: string[] = [];
  for (const folderId of value) {
    const decoded = nonEmptyString(folderId, 191);
    if (decoded === null) return null;
    folders.push(decoded);
  }
  return folders;
}

function librarySort(
  value: unknown,
): UserPreferences['librarySort'] | null {
  switch (value) {
    case undefined:
    case 'recent_read':
    case 'recent_import':
    case 'title':
    case 'author':
    case 'publisher':
    case 'series':
      return value;
    default:
      return null;
  }
}

function decodeUser(value: unknown): AuthenticatedUser | null {
  if (!isRecord(value) || !hasOnlyKeys(value, USER_KEYS)) {
    return null;
  }
  const id = nonEmptyString(value.id, 191);
  const email = nonEmptyString(value.email, 320);
  const name = nonEmptyString(value.name, 40);
  const authzVersion = nonNegativeSafeInteger(value.authzVersion);
  const userLocale =
    value.locale === undefined || value.locale === null
      ? null
      : locale(value.locale);
  const avatarUrl =
    value.avatarUrl === null ? null : nonEmptyString(value.avatarUrl, 2_048);
  if (
    id === null ||
    email === null ||
    name === null ||
    (value.role !== 'admin' && value.role !== 'member') ||
    (value.status !== 'active' && value.status !== 'disabled') ||
    typeof value.canManageSystem !== 'boolean' ||
    typeof value.canViewManualImports !== 'boolean' ||
    authzVersion === null ||
    (avatarUrl === null && value.avatarUrl !== null) ||
    (userLocale === null &&
      value.locale !== undefined &&
      value.locale !== null)
  ) {
    return null;
  }
  return {
    id,
    email,
    name,
    role: value.role,
    status: value.status,
    canManageSystem: value.canManageSystem,
    canViewManualImports: value.canViewManualImports,
    authzVersion,
    avatarUrl,
    locale: userLocale,
  };
}

function decodeAuthorization(value: unknown): AuthorizationSnapshot | null {
  if (!isRecord(value) || !hasOnlyKeys(value, AUTHORIZATION_KEYS)) {
    return null;
  }
  const authzVersion = nonNegativeSafeInteger(value.authzVersion);
  const folders = monitorFolderIds(value.monitorFolderIds);
  if (
    typeof value.isAdmin !== 'boolean' ||
    typeof value.canManageSystem !== 'boolean' ||
    typeof value.allLibraryScopes !== 'boolean' ||
    folders === null ||
    typeof value.canViewManualImports !== 'boolean' ||
    authzVersion === null
  ) {
    return null;
  }
  return {
    isAdmin: value.isAdmin,
    canManageSystem: value.canManageSystem,
    allLibraryScopes: value.allLibraryScopes,
    monitorFolderIds: folders,
    canViewManualImports: value.canViewManualImports,
    authzVersion,
  };
}

function decodePreferences(value: unknown): UserPreferences | null {
  if (!isRecord(value) || !hasOnlyKeys(value, PREFERENCE_KEYS)) {
    return null;
  }
  const activeLocale = locale(value.locale);
  const libraryView = value['library.view'];
  const activeLibrarySort = librarySort(value['library.sort']);
  const librarySortDirection = value['library.sortDirection'];
  const playbackRate = value['audio.playbackRate'];
  const activePlaybackRate =
    playbackRate === undefined
      ? undefined
      : finiteNumberInRange(playbackRate, 0.5, 3);
  const kindleEmail = value['kindle.email'];
  if (
    activeLocale === null ||
    (libraryView !== undefined &&
      libraryView !== 'grid' &&
      libraryView !== 'list') ||
    activeLibrarySort === null ||
    (librarySortDirection !== undefined &&
      librarySortDirection !== 'asc' &&
      librarySortDirection !== 'desc') ||
    activePlaybackRate === null ||
    (kindleEmail !== undefined && typeof kindleEmail !== 'string')
  ) {
    return null;
  }
  return {
    locale: activeLocale,
    ...(libraryView === undefined ? {} : { libraryView }),
    ...(activeLibrarySort === undefined
      ? {}
      : { librarySort: activeLibrarySort }),
    ...(librarySortDirection === undefined
      ? {}
      : { librarySortDirection }),
    ...(activePlaybackRate === undefined
      ? {}
      : { audioPlaybackRate: activePlaybackRate }),
    ...(kindleEmail === undefined ? {} : { kindleEmail }),
  };
}

export function decodeSessionEnvelope(
  value: unknown,
): ValidationResult<AuthenticatedSession> {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ENVELOPE_KEYS) ||
    value.ok !== true ||
    !isRecord(value.data) ||
    !hasOnlyKeys(value.data, SESSION_KEYS)
  ) {
    return { ok: false, reason: 'INVALID_SESSION_ENVELOPE' };
  }
  const user = decodeUser(value.data.user);
  const authorization = decodeAuthorization(value.data.authorization);
  const preferences = decodePreferences(value.data.preferences);
  if (user === null || authorization === null || preferences === null) {
    return { ok: false, reason: 'INVALID_SESSION_ENVELOPE' };
  }
  return { ok: true, value: { user, authorization, preferences } };
}

export function decodeSetupStatusEnvelope(
  value: unknown,
): ValidationResult<Readonly<{ initialized: boolean }>> {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ENVELOPE_KEYS) ||
    value.ok !== true ||
    !isRecord(value.data) ||
    !hasOnlyKeys(value.data, SETUP_KEYS) ||
    typeof value.data.initialized !== 'boolean'
  ) {
    return { ok: false, reason: 'INVALID_SETUP_STATUS_ENVELOPE' };
  }
  return { ok: true, value: { initialized: value.data.initialized } };
}

export function decodeLoggedOutEnvelope(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ENVELOPE_KEYS) &&
    value.ok === true &&
    isRecord(value.data) &&
    hasOnlyKeys(value.data, LOGOUT_KEYS) &&
    value.data.loggedOut === true
  );
}

export function errorCode(value: unknown): string | null {
  if (!isRecord(value) || value.ok !== false || !isRecord(value.error)) {
    return null;
  }
  if (typeof value.error.code === 'string') {
    return value.error.code;
  }
  return isRecord(value.error.details) &&
    typeof value.error.details.code === 'string'
    ? value.error.details.code
    : null;
}

export type SupportedLocale = 'en-US' | 'zh-CN';

export type AuthenticatedUser = Readonly<{
  id: string;
  email: string;
  name: string;
  role: 'admin' | 'member';
  status: 'active' | 'disabled';
  canManageSystem: boolean;
  canViewManualImports: boolean;
  authzVersion: number;
  avatarUrl: string | null;
  locale: SupportedLocale | null;
}>;

export type AuthorizationSnapshot = Readonly<{
  isAdmin: boolean;
  canManageSystem: boolean;
  allLibraryScopes: boolean;
  monitorFolderIds: readonly string[];
  canViewManualImports: boolean;
  authzVersion: number;
}>;

export type UserPreferences = Readonly<{
  locale: SupportedLocale;
  libraryView?: 'grid' | 'list';
  librarySort?:
    | 'recent_read'
    | 'recent_import'
    | 'title'
    | 'author'
    | 'publisher'
    | 'series';
  librarySortDirection?: 'asc' | 'desc';
  audioPlaybackRate?: number;
  kindleEmail?: string;
}>;

export type AuthenticatedSession = Readonly<{
  user: AuthenticatedUser;
  authorization: AuthorizationSnapshot;
  preferences: UserPreferences;
}>;

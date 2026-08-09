import type { Href } from 'expo-router';

import type { MessageKey } from '../shared/i18n/public';
import type { AppIconName } from '../shared/ui/public';

export const shellRoutes = ['home', 'library', 'me'] as const;

export type ShellRoute = (typeof shellRoutes)[number];

export type ShellRouteDefinition = Readonly<{
  hintKey: MessageKey;
  iconName: AppIconName;
  labelKey: MessageKey;
  path: Href;
}>;

export const shellRouteDefinitions: Readonly<
  Record<ShellRoute, ShellRouteDefinition>
> = {
  home: {
    hintKey: 'route.home.hint',
    iconName: 'home',
    labelKey: 'route.home.label',
    path: '/home',
  },
  library: {
    hintKey: 'route.library.hint',
    iconName: 'library',
    labelKey: 'route.library.label',
    path: '/library',
  },
  me: {
    hintKey: 'route.me.hint',
    iconName: 'person',
    labelKey: 'route.me.label',
    path: '/me',
  },
};

export function shellRouteForPath(pathname: string): ShellRoute {
  if (
    pathname.startsWith('/library') ||
    pathname.startsWith('/reader')
  ) {
    return 'library';
  }
  if (pathname.startsWith('/me')) return 'me';
  return 'home';
}

export function shouldUseExpandedNavigation({
  availableWidth,
  expandedMinimumWidth,
  fontScale,
}: Readonly<{
  availableWidth: number;
  expandedMinimumWidth: number;
  fontScale: number;
}>): boolean {
  const effectiveFontScale = Math.max(1, fontScale);
  return availableWidth / effectiveFontScale >= expandedMinimumWidth;
}

import { Redirect, Slot } from 'expo-router';
import type { ReactNode } from 'react';
import { Text } from 'react-native';

import type { AuthenticatedSession } from '../../src/features/identity/public';
import { I18nProvider } from '../../src/shared/i18n/public';
import { AppThemeProvider } from '../../src/shared/ui/public';
import {
  appFlowAnchorHref,
  ProtectedApplicationRoutes,
  ProtectedConnectionRoutes,
  type AppFlowState,
} from '../../src/features/app-flow/public';
import {
  parseServerAddress,
  type ServerProfile,
} from '../../src/features/server-connection/public';

export function profile(): ServerProfile {
  const parsed = parseServerAddress('https://books.example.com');
  if (!parsed.ok) throw new Error('Test library web address must be valid');
  return {
    id: 'profile-1',
    baseUrl: parsed.baseUrl,
    service: 'ermao-books',
    initialized: true,
    createdAtMs: 1,
    lastVerifiedAtMs: 1,
  };
}

export function session(): AuthenticatedSession {
  return {
    user: {
      id: 'user-1',
      email: 'reader@example.com',
      name: 'Reader',
      role: 'member',
      status: 'active',
      canManageSystem: false,
      canViewManualImports: false,
      authzVersion: 1,
      avatarUrl: null,
      locale: 'en-US',
    },
    authorization: {
      isAdmin: false,
      canManageSystem: false,
      allLibraryScopes: false,
      monitorFolderIds: [],
      canViewManualImports: false,
      authzVersion: 1,
    },
    preferences: { locale: 'en-US' },
  };
}

export function routes(state: AppFlowState) {
  function RootLayout(): ReactNode {
    return <ProtectedApplicationRoutes state={state} />;
  }
  function ConnectionLayout(): ReactNode {
    return (
      <AppThemeProvider colorScheme="light">
        <I18nProvider>
          <ProtectedConnectionRoutes state={state} />
        </I18nProvider>
      </AppThemeProvider>
    );
  }
  function Anchor(): ReactNode {
    const href = appFlowAnchorHref(state);
    return href === null ? <Text>recovery</Text> : <Redirect href={href} />;
  }
  function GroupLayout(): ReactNode {
    return <Slot />;
  }
  const Connect = () => <Text>connect</Text>;
  const Address = () => <Text>address</Text>;
  const Scan = () => <Text>scan</Text>;
  const Connections = () => <Text>connections</Text>;
  const Login = () => <Text>login</Text>;
  const Home = () => <Text>home</Text>;
  const Library = () => <Text>library</Text>;
  const Me = () => <Text>me</Text>;
  const Reader = () => <Text>reader</Text>;

  return {
    _layout: RootLayout,
    index: Anchor,
    '(connection)/_layout': ConnectionLayout,
    '(connection)/connect': Connect,
    '(connection)/address': Address,
    '(connection)/scan': Scan,
    '(connection)/connections': Connections,
    '(auth)/_layout': GroupLayout,
    '(auth)/login': Login,
    '(main)/_layout': GroupLayout,
    '(main)/home': Home,
    '(main)/library': Library,
    '(main)/me': Me,
    reader: Reader,
  };
}

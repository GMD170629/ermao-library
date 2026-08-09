import {
  useCallback,
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { useColorScheme } from 'react-native';

import type {
  ThemePreference,
  ThemePreferenceStore,
} from '../preferences/theme-preference';
import { appTheme, type AppTheme, type ColorScheme } from './theme';

export type AppThemeController = Readonly<{
  colorScheme: ColorScheme;
  preference: ThemePreference;
  setPreference(preference: ThemePreference): void;
  theme: AppTheme;
  toggleColorScheme(): void;
}>;

const AppThemeContext = createContext<AppThemeController | null>(null);

export type AppThemeProviderProps = Readonly<{
  children: ReactNode;
  colorScheme?: ColorScheme;
  preferenceStore?: ThemePreferenceStore;
}>;

export function AppThemeProvider({
  children,
  colorScheme,
  preferenceStore,
}: AppThemeProviderProps): ReactNode {
  const systemColorScheme = useColorScheme();
  const [preference, setPreferenceState] = useState<ThemePreference>(() => {
    if (colorScheme !== undefined) return colorScheme;
    try {
      return preferenceStore?.load() ?? 'system';
    } catch {
      return 'system';
    }
  });

  const systemScheme: ColorScheme =
    systemColorScheme === 'dark' ? 'dark' : 'light';
  const resolvedScheme =
    colorScheme ?? (preference === 'system' ? systemScheme : preference);
  const setPreference = useCallback(
    (nextPreference: ThemePreference): void => {
      setPreferenceState(nextPreference);
      void preferenceStore?.save(nextPreference).catch(() => undefined);
    },
    [preferenceStore],
  );
  const toggleColorScheme = useCallback((): void => {
    setPreference(resolvedScheme === 'dark' ? 'light' : 'dark');
  }, [resolvedScheme, setPreference]);
  const value = useMemo<AppThemeController>(
    () => ({
      colorScheme: resolvedScheme,
      preference,
      setPreference,
      theme: appTheme(resolvedScheme),
      toggleColorScheme,
    }),
    [preference, resolvedScheme, setPreference, toggleColorScheme],
  );

  return (
    <AppThemeContext.Provider value={value}>
      {children}
    </AppThemeContext.Provider>
  );
}

export function useAppTheme(): AppTheme {
  const controller = useContext(AppThemeContext);
  const systemColorScheme = useColorScheme();
  return (
    controller?.theme ??
    appTheme(systemColorScheme === 'dark' ? 'dark' : 'light')
  );
}

export function useAppThemeController(): AppThemeController {
  const controller = useContext(AppThemeContext);
  if (controller === null) {
    throw new Error(
      'useAppThemeController must be used within AppThemeProvider',
    );
  }
  return controller;
}

import {
  AppState,
  type AppStateStatus,
} from 'react-native';
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from 'react';

import type { AppFlowController } from '../application/app-flow-controller';
import type { SignInCommand } from '../application/ports';
import type { AppFlowState } from '../model/app-flow-state';

export type AppFlowContextValue = Readonly<{
  state: AppFlowState;
  connect(candidate: string, source: 'manual' | 'qr'): Promise<void>;
  selectProfile(profileId: string): Promise<void>;
  profileRemoved(profileId: string): void;
  profilesReset(): void;
  cancelPendingConnection(): void;
  cancelPendingLogin(): void;
  signIn(command: SignInCommand): Promise<void>;
  logout(): Promise<void>;
  logoutForConnectionManagement(): Promise<void>;
  sessionExpired(): void;
}>;

const AppFlowContext = createContext<AppFlowContextValue | null>(null);

export type AppFlowProviderProps = Readonly<{
  children: ReactNode;
  controller: AppFlowController;
}>;

export function AppFlowProvider({
  children,
  controller,
}: AppFlowProviderProps): ReactNode {
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );

  useEffect(() => {
    void controller.start();
    return () => controller.dispose();
  }, [controller]);

  useEffect(() => {
    let previousState: AppStateStatus = AppState.currentState;
    const subscription = AppState.addEventListener('change', (nextState) => {
      if (previousState !== 'active' && nextState === 'active') {
        void controller.restoreOnForeground();
      }
      previousState = nextState;
    });
    return () => subscription.remove();
  }, [controller]);

  const actions = useMemo<Omit<AppFlowContextValue, 'state'>>(
    () => ({
      connect: (candidate, source) => controller.connect(candidate, source),
      selectProfile: (profileId) => controller.selectProfile(profileId),
      profileRemoved: (profileId) => controller.profileRemoved(profileId),
      profilesReset: () => controller.profilesReset(),
      cancelPendingConnection: () => controller.cancelPendingConnection(),
      cancelPendingLogin: () => controller.cancelPendingLogin(),
      signIn: (command) => controller.signIn(command),
      logout: () => controller.logout(),
      logoutForConnectionManagement: () =>
        controller.logoutForConnectionManagement(),
      sessionExpired: () => controller.sessionExpired(),
    }),
    [controller],
  );
  const value = useMemo<AppFlowContextValue>(
    () => ({ state, ...actions }),
    [actions, state],
  );

  return (
    <AppFlowContext.Provider value={value}>
      {children}
    </AppFlowContext.Provider>
  );
}

export function useAppFlow(): AppFlowContextValue {
  const value = useContext(AppFlowContext);
  if (value === null) {
    throw new Error('useAppFlow must be used within AppFlowProvider');
  }
  return value;
}

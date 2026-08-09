import type {
  AppFlowCancellationFactory,
  AppFlowCancellationSource,
  AppFlowGateway,
  SignInCommand,
} from './ports';
import type {
  AppFlowFailure,
  AppFlowState,
  AuthenticatedState,
  SignedOutState,
} from '../model/app-flow-state';
import type {
  ServerProfile,
  ServerProfilePersistenceWarning,
} from '../../server-connection/public';

type Operation = Readonly<{
  sequence: number;
  cancellation: AppFlowCancellationSource;
}>;

type Listener = () => void;

function signedOut(
  command: Readonly<{
    profile: ServerProfile | null;
    reason: SignedOutState['reason'];
    profileWarnings: readonly ServerProfilePersistenceWarning[];
    serverAddress?: string;
    email?: string;
    warning?: AppFlowFailure;
    access?: SignedOutState['access'];
  }>,
): SignedOutState {
  const access =
    command.access ??
    (command.profile?.initialized === false ? 'setup-required' : 'ready');
  return {
    phase: 'signed-out',
    profile: command.profile,
    serverAddress:
      command.serverAddress ?? command.profile?.baseUrl.value ?? '',
    email: command.email ?? '',
    access,
    reason:
      access === 'setup-required'
        ? 'server-setup-required'
        : command.reason,
    profileWarnings: command.profileWarnings,
    ...(command.warning === undefined ? {} : { warning: command.warning }),
  };
}

export class AppFlowController {
  private state: AppFlowState = { phase: 'loading-profile' };
  private readonly listeners = new Set<Listener>();
  private operationSequence = 0;
  private currentOperation: Operation | null = null;

  constructor(
    private readonly gateway: AppFlowGateway,
    private readonly cancellations: AppFlowCancellationFactory,
  ) {}

  readonly getSnapshot = (): AppFlowState => this.state;

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  async start(): Promise<void> {
    const operation = this.beginOperation();
    this.publish({ phase: 'loading-profile' });
    const activeProfile = await this.gateway.loadActiveProfile(
      operation.cancellation.token,
    );
    if (!this.isCurrent(operation)) return;
    if (activeProfile.outcome === 'failed') {
      this.publish(
        signedOut({
          profile: null,
          reason: 'no-session',
          profileWarnings: [],
          warning: activeProfile.failure,
        }),
      );
      return;
    }
    if (activeProfile.profile === null) {
      this.publish(
        signedOut({
          profile: null,
          reason: 'no-session',
          profileWarnings: activeProfile.warnings,
        }),
      );
      return;
    }
    await this.recheckAndRestore(
      activeProfile.profile,
      operation,
      activeProfile.warnings,
    );
  }

  async connect(
    candidate: string,
    source: 'manual' | 'qr',
  ): Promise<void> {
    const operation = this.beginOperation();
    const profileWarnings =
      this.state.phase === 'connection-required'
        ? this.state.profileWarnings
        : [];
    this.publish({
      phase: 'connecting',
      intent: 'connection',
      candidate,
      source,
      profileWarnings,
    });
    const connected = await this.gateway.connect(
      candidate,
      source,
      operation.cancellation.token,
    );
    if (!this.isCurrent(operation)) return;
    if (connected.outcome === 'failed') {
      this.publish({
        phase: 'connection-required',
        profileWarnings,
        failure: connected.failure,
      });
      return;
    }
    if (!connected.profile.initialized) {
      this.publish(
        signedOut({
          profile: connected.profile,
          reason: 'server-setup-required',
          profileWarnings: connected.warnings,
        }),
      );
      return;
    }
    await this.restoreForInteractiveFlow(
      connected.profile,
      connected.warnings,
      operation,
    );
  }

  async selectProfile(profileId: string): Promise<void> {
    const operation = this.beginOperation();
    const profileWarnings = this.profileWarnings(this.state);
    this.publish({
      phase: 'selecting-profile',
      profileId,
      profileWarnings,
    });
    const selected = await this.gateway.selectProfile(
      profileId,
      operation.cancellation.token,
    );
    if (!this.isCurrent(operation)) return;
    if (selected.outcome === 'failed') {
      this.publish({
        phase: 'connection-required',
        profileWarnings,
        failure: selected.failure,
      });
      return;
    }
    if (!selected.profile.initialized) {
      this.publish(
        signedOut({
          profile: selected.profile,
          reason: 'server-setup-required',
          profileWarnings: selected.warnings,
        }),
      );
      return;
    }
    await this.restoreForInteractiveFlow(
      selected.profile,
      selected.warnings,
      operation,
    );
  }

  profileRemoved(profileId: string): void {
    const currentProfile = this.profileFromState(this.state);
    const selectingRemovedProfile =
      this.state.phase === 'selecting-profile' &&
      this.state.profileId === profileId;
    if (currentProfile?.id !== profileId && !selectingRemovedProfile) return;
    const profileWarnings = this.profileWarnings(this.state);
    this.dispose();
    this.publish(
      signedOut({ profile: null, reason: 'no-session', profileWarnings }),
    );
  }

  profilesReset(): void {
    this.dispose();
    this.publish(
      signedOut({ profile: null, reason: 'no-session', profileWarnings: [] }),
    );
  }

  cancelPendingConnection(): void {
    if (
      this.state.phase === 'connection-required' &&
      this.state.failure !== undefined
    ) {
      this.publish({
        phase: 'connection-required',
        profileWarnings: this.state.profileWarnings,
      });
      return;
    }
    if (
      (this.state.phase !== 'connecting' ||
        this.state.intent !== 'connection') &&
      this.state.phase !== 'selecting-profile'
    ) {
      return;
    }
    const profileWarnings = this.state.profileWarnings;
    this.dispose();
    this.publish({ phase: 'connection-required', profileWarnings });
  }

  cancelPendingLogin(): void {
    const current = this.state;
    if (
      current.phase !== 'authenticating' &&
      (current.phase !== 'connecting' || current.intent !== 'sign-in')
    ) {
      return;
    }
    this.dispose();
    this.publish(
      signedOut({
        profile: current.profile,
        reason: 'no-session',
        profileWarnings: current.profileWarnings,
        serverAddress: current.serverAddress,
        email: current.email,
      }),
    );
  }

  async signIn(command: SignInCommand): Promise<void> {
    const current = this.state;
    if (current.phase !== 'signed-out') return;

    const operation = this.beginOperation();
    this.publish({
      phase: 'connecting',
      intent: 'sign-in',
      candidate: command.serverAddress,
      source: 'manual',
      profile: current.profile,
      serverAddress: command.serverAddress,
      email: command.email,
      profileWarnings: current.profileWarnings,
    });
    const connected = await this.gateway.connect(
      command.serverAddress,
      'manual',
      operation.cancellation.token,
    );
    if (!this.isCurrent(operation)) return;
    if (connected.outcome === 'failed') {
      this.publish(
        signedOut({
          profile: current.profile,
          reason: current.reason,
          profileWarnings: current.profileWarnings,
          serverAddress: command.serverAddress,
          email: command.email,
          warning: connected.failure,
        }),
      );
      return;
    }
    if (!connected.profile.initialized) {
      this.publish(
        signedOut({
          profile: connected.profile,
          reason: 'server-setup-required',
          profileWarnings: connected.warnings,
          serverAddress: command.serverAddress,
          email: command.email,
        }),
      );
      return;
    }
    await this.authenticate(
      connected.profile,
      connected.warnings,
      command.serverAddress,
      command.email,
      command.password,
      operation,
    );
  }

  async restoreOnForeground(): Promise<void> {
    const current = this.state;
    if (current.phase === 'authenticated') {
      await this.refreshAuthenticatedSession(current);
      return;
    }
    if (
      current.phase === 'signed-out' &&
      current.profile !== null &&
      current.access === 'ready' &&
      current.reason !== 'connection-management-requested'
    ) {
      const operation = this.beginOperation();
      await this.restoreSignedOutSession(current, operation);
    }
  }

  async logout(): Promise<void> {
    await this.logoutWithIntent('sign-out');
  }

  async logoutForConnectionManagement(): Promise<void> {
    await this.logoutWithIntent('manage-connections');
  }

  sessionExpired(): void {
    const current = this.state;
    if (
      current.phase !== 'authenticated' &&
      current.phase !== 'logging-out'
    ) {
      return;
    }
    this.dispose();
    this.publish(
      signedOut({
        profile: current.profile,
        reason: 'session-expired',
        profileWarnings: current.profileWarnings,
      }),
    );
  }

  private async logoutWithIntent(
    intent: 'manage-connections' | 'sign-out',
  ): Promise<void> {
    const current = this.state;
    if (current.phase !== 'authenticated') return;
    const operation = this.beginOperation();
    this.publish({
      phase: 'logging-out',
      intent,
      profile: current.profile,
      session: current.session,
      profileWarnings: current.profileWarnings,
    });
    const result = await this.gateway.logout(
      current.profile,
      operation.cancellation.token,
    );
    if (!this.isCurrent(operation)) return;
    if (result.outcome === 'logged-out') {
      this.publish(
        signedOut({
          profile: current.profile,
          reason:
            intent === 'manage-connections'
              ? 'connection-management-requested'
              : 'logout-confirmed',
          profileWarnings: current.profileWarnings,
        }),
      );
      return;
    }
    this.publish({
      phase: 'authenticated',
      profile: current.profile,
      session: current.session,
      freshness: 'stale',
      profileWarnings: current.profileWarnings,
      warning: result.failure,
    });
  }

  dispose(): void {
    this.operationSequence += 1;
    this.currentOperation?.cancellation.cancel();
    this.currentOperation = null;
  }

  private async authenticate(
    profile: ServerProfile,
    profileWarnings: readonly ServerProfilePersistenceWarning[],
    serverAddress: string,
    email: string,
    password: string,
    operation: Operation,
  ): Promise<void> {
    this.publish({
      phase: 'authenticating',
      profile,
      serverAddress,
      email,
      profileWarnings,
    });
    const result = await this.gateway.login(
      profile,
      { email, password },
      operation.cancellation.token,
    );
    if (!this.isCurrent(operation)) return;
    if (result.outcome === 'authenticated') {
      this.publish({
        phase: 'authenticated',
        profile,
        session: result.session,
        freshness: 'fresh',
        profileWarnings,
      });
      return;
    }
    if (result.outcome === 'rejected') {
      const setupRequired = result.reason === 'setup-required';
      this.publish(
        signedOut({
          profile,
          reason: setupRequired ? 'server-setup-required' : 'no-session',
          profileWarnings,
          serverAddress,
          email,
          warning: {
            area: 'session',
            operation: 'login',
            reason: result.reason,
          },
          access: setupRequired ? 'setup-required' : 'ready',
        }),
      );
      return;
    }
    this.publish(
      signedOut({
        profile,
        reason: 'no-session',
        profileWarnings,
        serverAddress,
        email,
        warning: result.failure,
      }),
    );
  }

  private async recheckAndRestore(
    profile: ServerProfile,
    operation: Operation,
    loadedWarnings: readonly ServerProfilePersistenceWarning[],
  ): Promise<void> {
    this.publish({
      phase: 'verifying-server',
      profile,
      profileWarnings: loadedWarnings,
    });
    const checked = await this.gateway.recheckProfile(
      profile,
      operation.cancellation.token,
    );
    if (!this.isCurrent(operation)) return;
    const profileWarnings = [
      ...loadedWarnings,
      ...(checked.outcome === 'connected' ? checked.warnings : []),
    ];
    if (checked.outcome === 'failed') {
      this.publish(
        signedOut({
          profile,
          reason: 'no-session',
          profileWarnings,
          warning: checked.failure,
        }),
      );
      return;
    }
    if (!checked.profile.initialized) {
      this.publish(
        signedOut({
          profile: checked.profile,
          reason: 'server-setup-required',
          profileWarnings,
        }),
      );
      return;
    }
    this.publish({
      phase: 'restoring-session',
      profile: checked.profile,
      profileWarnings,
    });
    const restored = await this.gateway.restoreSession(
      checked.profile,
      operation.cancellation.token,
    );
    if (!this.isCurrent(operation)) return;
    if (restored.outcome === 'authenticated') {
      this.publish({
        phase: 'authenticated',
        profile: checked.profile,
        session: restored.session,
        freshness: 'fresh',
        profileWarnings,
      });
      return;
    }
    if (restored.outcome === 'unauthenticated') {
      this.publish(
        signedOut({
          profile: checked.profile,
          reason: 'no-session',
          profileWarnings,
        }),
      );
      return;
    }
    this.publish(
      signedOut({
        profile: checked.profile,
        reason: 'no-session',
        profileWarnings,
        warning: restored.failure,
      }),
    );
  }

  private async restoreForInteractiveFlow(
    profile: ServerProfile,
    profileWarnings: readonly ServerProfilePersistenceWarning[],
    operation: Operation,
  ): Promise<void> {
    this.publish({
      phase: 'restoring-session',
      profile,
      profileWarnings,
    });
    const restored = await this.gateway.restoreSession(
      profile,
      operation.cancellation.token,
    );
    if (!this.isCurrent(operation)) return;
    if (restored.outcome === 'authenticated') {
      this.publish({
        phase: 'authenticated',
        profile,
        session: restored.session,
        freshness: 'fresh',
        profileWarnings,
      });
      return;
    }
    if (restored.outcome === 'unauthenticated') {
      this.publish(
        signedOut({ profile, reason: 'no-session', profileWarnings }),
      );
      return;
    }
    this.publish(
      signedOut({
        profile,
        reason: 'no-session',
        profileWarnings,
        warning: restored.failure,
      }),
    );
  }

  private async refreshAuthenticatedSession(
    current: AuthenticatedState,
  ): Promise<void> {
    const operation = this.beginOperation();
    this.publish({ ...current, freshness: 'checking' });
    const restored = await this.gateway.restoreSession(
      current.profile,
      operation.cancellation.token,
    );
    if (!this.isCurrent(operation)) return;
    if (restored.outcome === 'authenticated') {
      this.publish({
        phase: 'authenticated',
        profile: current.profile,
        session: restored.session,
        freshness: 'fresh',
        profileWarnings: current.profileWarnings,
      });
      return;
    }
    if (restored.outcome === 'unauthenticated') {
      this.publish(
        signedOut({
          profile: current.profile,
          reason: 'no-session',
          profileWarnings: current.profileWarnings,
        }),
      );
      return;
    }
    this.publish({
      phase: 'authenticated',
      profile: current.profile,
      session: current.session,
      freshness: 'stale',
      profileWarnings: current.profileWarnings,
      warning: restored.failure,
    });
  }

  private async restoreSignedOutSession(
    current: SignedOutState,
    operation: Operation,
  ): Promise<void> {
    if (current.profile === null) return;
    const profile = current.profile;
    const restored = await this.gateway.restoreSession(
      profile,
      operation.cancellation.token,
    );
    if (!this.isCurrent(operation)) return;
    if (restored.outcome === 'authenticated') {
      this.publish({
        phase: 'authenticated',
        profile,
        session: restored.session,
        freshness: 'fresh',
        profileWarnings: current.profileWarnings,
      });
      return;
    }
    if (restored.outcome === 'unauthenticated') {
      this.publish(
        signedOut({
          profile,
          reason: 'no-session',
          profileWarnings: current.profileWarnings,
          serverAddress: current.serverAddress,
          email: current.email,
        }),
      );
      return;
    }
    this.publish(
      signedOut({
        profile,
        reason: current.reason,
        profileWarnings: current.profileWarnings,
        serverAddress: current.serverAddress,
        email: current.email,
        warning: restored.failure,
      }),
    );
  }

  private beginOperation(): Operation {
    this.currentOperation?.cancellation.cancel();
    const operation = {
      sequence: this.operationSequence + 1,
      cancellation: this.cancellations.create(),
    };
    this.operationSequence = operation.sequence;
    this.currentOperation = operation;
    return operation;
  }

  private profileFromState(state: AppFlowState): ServerProfile | null {
    switch (state.phase) {
      case 'signed-out':
      case 'authenticating':
      case 'authenticated':
      case 'logging-out':
      case 'verifying-server':
      case 'restoring-session':
        return state.profile;
      case 'connecting':
        return state.intent === 'sign-in' ? state.profile : null;
      case 'loading-profile':
      case 'connection-required':
      case 'selecting-profile':
        return null;
    }
  }

  private profileWarnings(
    state: AppFlowState,
  ): readonly ServerProfilePersistenceWarning[] {
    return state.phase === 'loading-profile' ? [] : state.profileWarnings;
  }

  private isCurrent(operation: Operation): boolean {
    return (
      this.currentOperation === operation &&
      this.operationSequence === operation.sequence
    );
  }

  private publish(state: AppFlowState): void {
    this.state = state;
    this.listeners.forEach((listener) => listener());
  }
}

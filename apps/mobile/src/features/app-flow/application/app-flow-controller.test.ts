import assert from 'node:assert/strict';
import test from 'node:test';

import type { AuthenticatedSession } from '../../identity/public';
import {
  parseServerAddress,
  type CancellationToken,
  type ServerProfile,
} from '../../server-connection/public';
import { AppFlowController as ProductionAppFlowController } from './app-flow-controller';
import type {
  ActiveProfileResult,
  AppFlowCancellationFactory,
  AppFlowCancellationSource,
  AppFlowGateway,
  ConnectProfileResult,
  LoginFlowResult,
  LogoutFlowResult,
  RestoreFlowSessionResult,
} from './ports';

class TestCancellationSource implements AppFlowCancellationSource {
  private cancelled = false;
  private readonly listeners = new Set<() => void>();
  readonly token: CancellationToken = {
    isCancellationRequested: () => this.cancelled,
    subscribe: (listener) => {
      this.listeners.add(listener);
      return () => this.listeners.delete(listener);
    },
  };

  cancel(): void {
    this.cancelled = true;
    this.listeners.forEach((listener) => listener());
  }
}

class TestCancellationFactory implements AppFlowCancellationFactory {
  create(): AppFlowCancellationSource {
    return new TestCancellationSource();
  }
}

class AppFlowController extends ProductionAppFlowController {
  constructor(gateway: AppFlowGateway) {
    super(gateway, new TestCancellationFactory());
  }
}

type Deferred<Value> = Readonly<{
  promise: Promise<Value>;
  resolve(value: Value): void;
}>;

function deferred<Value>(): Deferred<Value> {
  let resolvePromise: ((value: Value) => void) | undefined;
  const promise = new Promise<Value>((resolve) => {
    resolvePromise = resolve;
  });
  return {
    promise,
    resolve(value) {
      if (resolvePromise === undefined) {
        throw new Error('Deferred promise is unavailable');
      }
      resolvePromise(value);
    },
  };
}

function profile(
  initialized = true,
  serverAddress = 'https://books.example.com',
  id = 'profile-1',
): ServerProfile {
  const parsed = parseServerAddress(serverAddress);
  if (!parsed.ok) throw new Error('Test library web address must be valid');
  return {
    id,
    baseUrl: parsed.baseUrl,
    service: 'ermao-books',
    initialized,
    createdAtMs: 1,
    lastVerifiedAtMs: 1,
  };
}

function session(name = 'Reader'): AuthenticatedSession {
  return {
    user: {
      id: 'user-1',
      email: 'reader@example.com',
      name,
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

class FakeAppFlowGateway implements AppFlowGateway {
  activeProfileResult: ActiveProfileResult = {
    outcome: 'loaded',
    profile: null,
    warnings: [],
  };
  connectResult: ConnectProfileResult = {
    outcome: 'connected',
    profile: profile(),
    warnings: [],
  };
  recheckResult: ConnectProfileResult = this.connectResult;
  restoreResult: RestoreFlowSessionResult = { outcome: 'unauthenticated' };
  loginResult: LoginFlowResult = {
    outcome: 'authenticated',
    session: session(),
  };
  connectDeferred: Deferred<ConnectProfileResult> | null = null;
  loginDeferred: Deferred<LoginFlowResult> | null = null;
  connectCandidates: string[] = [];
  connectSources: ('manual' | 'qr')[] = [];
  loginCancellations: CancellationToken[] = [];
  loginProfiles: ServerProfile[] = [];
  loginCredentials: Readonly<{ email: string; password: string }> | null = null;
  logoutResult: LogoutFlowResult = { outcome: 'logged-out' };
  logoutDeferred: Deferred<LogoutFlowResult> | null = null;
  activeProfileDeferred: Deferred<ActiveProfileResult> | null = null;
  connectCancellations: CancellationToken[] = [];

  loadActiveProfile(
    _cancellation: CancellationToken,
  ): Promise<ActiveProfileResult> {
    return this.activeProfileDeferred?.promise ?? Promise.resolve(this.activeProfileResult);
  }

  recheckProfile(
    _profile: ServerProfile,
    _cancellation: CancellationToken,
  ): Promise<ConnectProfileResult> {
    return Promise.resolve(this.recheckResult);
  }

  selectProfile(
    _profileId: string,
    _cancellation: CancellationToken,
  ): Promise<ConnectProfileResult> {
    return Promise.resolve(this.recheckResult);
  }

  connect(
    candidate: string,
    source: 'manual' | 'qr',
    cancellation: CancellationToken,
  ): Promise<ConnectProfileResult> {
    this.connectCandidates.push(candidate);
    this.connectSources.push(source);
    this.connectCancellations.push(cancellation);
    return this.connectDeferred?.promise ?? Promise.resolve(this.connectResult);
  }

  restoreSession(
    _profile: ServerProfile,
    _cancellation: CancellationToken,
  ): Promise<RestoreFlowSessionResult> {
    return Promise.resolve(this.restoreResult);
  }

  login(
    loginProfile: ServerProfile,
    credentials: Readonly<{ email: string; password: string }>,
    cancellation: CancellationToken,
  ): Promise<LoginFlowResult> {
    this.loginProfiles.push(loginProfile);
    this.loginCredentials = credentials;
    this.loginCancellations.push(cancellation);
    return this.loginDeferred?.promise ?? Promise.resolve(this.loginResult);
  }

  logout(
    _profile: ServerProfile,
    _cancellation: CancellationToken,
  ): Promise<LogoutFlowResult> {
    return this.logoutDeferred?.promise ?? Promise.resolve(this.logoutResult);
  }
}

test('cold start without an active profile opens unified sign in', async () => {
  const gateway = new FakeAppFlowGateway();
  const controller = new AppFlowController(gateway);

  await controller.start();

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'signed-out',
    profile: null,
    serverAddress: '',
    email: '',
    access: 'ready',
    reason: 'no-session',
    profileWarnings: [],
  });
});

test('profile load failure opens unified sign in instead of a recovery page', async () => {
  const gateway = new FakeAppFlowGateway();
  gateway.activeProfileResult = {
    outcome: 'failed',
    failure: {
      area: 'profile',
      operation: 'load-profile',
      reason: 'corrupt-local-data',
    },
  };
  const controller = new AppFlowController(gateway);

  await controller.start();

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'signed-out',
    profile: null,
    serverAddress: '',
    email: '',
    access: 'ready',
    reason: 'no-session',
    profileWarnings: [],
    warning: {
      area: 'profile',
      operation: 'load-profile',
      reason: 'corrupt-local-data',
    },
  });
});

test('cold start rechecks health and sends an uninitialized server to signed out', async () => {
  const gateway = new FakeAppFlowGateway();
  const uninitialized = profile(false);
  gateway.activeProfileResult = {
    outcome: 'loaded',
    profile: uninitialized,
    warnings: [],
  };
  gateway.recheckResult = {
    outcome: 'connected',
    profile: uninitialized,
    warnings: [],
  };
  const controller = new AppFlowController(gateway);

  await controller.start();

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'signed-out',
    profile: uninitialized,
    serverAddress: 'https://books.example.com',
    email: '',
    access: 'setup-required',
    reason: 'server-setup-required',
    profileWarnings: [],
  });
});

test('cold start restores the current Cookie session after health recheck', async () => {
  const gateway = new FakeAppFlowGateway();
  const activeProfile = profile();
  const restoredSession = session();
  gateway.activeProfileResult = {
    outcome: 'loaded',
    profile: activeProfile,
    warnings: [],
  };
  gateway.recheckResult = {
    outcome: 'connected',
    profile: activeProfile,
    warnings: [],
  };
  gateway.restoreResult = {
    outcome: 'authenticated',
    session: restoredSession,
  };
  const controller = new AppFlowController(gateway);

  await controller.start();

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'authenticated',
    profile: activeProfile,
    session: restoredSession,
    freshness: 'fresh',
    profileWarnings: [],
  });
});

test('cold start exposes non-blocking profile recovery warnings', async () => {
  const gateway = new FakeAppFlowGateway();
  const activeProfile = profile();
  gateway.activeProfileResult = {
    outcome: 'loaded',
    profile: activeProfile,
    warnings: [
      { kind: 'recovered-older-snapshot', rejectedNewerSnapshots: 1 },
    ],
  };
  gateway.recheckResult = {
    outcome: 'connected',
    profile: activeProfile,
    warnings: [{ kind: 'maintenance-cleanup-failed', issueCount: 2 }],
  };
  gateway.restoreResult = { outcome: 'authenticated', session: session() };
  const controller = new AppFlowController(gateway);

  await controller.start();

  const state = controller.getSnapshot();
  assert.equal(state.phase, 'authenticated');
  if (state.phase !== 'authenticated') return;
  assert.deepEqual(state.profileWarnings, [
    { kind: 'recovered-older-snapshot', rejectedNewerSnapshots: 1 },
    { kind: 'maintenance-cleanup-failed', issueCount: 2 },
  ]);
});

test('cold-start server failure opens unified sign in with the saved address', async () => {
  const gateway = new FakeAppFlowGateway();
  const activeProfile = profile();
  gateway.activeProfileResult = {
    outcome: 'loaded',
    profile: activeProfile,
    warnings: [],
  };
  gateway.recheckResult = {
    outcome: 'failed',
    failure: { area: 'server', operation: 'connect', reason: 'timeout' },
  };
  const controller = new AppFlowController(gateway);

  await controller.start();

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'signed-out',
    profile: activeProfile,
    serverAddress: activeProfile.baseUrl.value,
    email: '',
    access: 'ready',
    reason: 'no-session',
    profileWarnings: [],
    warning: { area: 'server', operation: 'connect', reason: 'timeout' },
  });
});

test('interactive session failure opens unified sign in for another attempt', async () => {
  const gateway = new FakeAppFlowGateway();
  const connectedProfile = profile();
  gateway.connectResult = {
    outcome: 'connected',
    profile: connectedProfile,
    warnings: [],
  };
  gateway.restoreResult = {
    outcome: 'failed',
    failure: { area: 'session', operation: 'restore', reason: 'network' },
  };
  const controller = new AppFlowController(gateway);
  await controller.start();

  await controller.connect('https://books.example.com', 'qr');

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'signed-out',
    profile: connectedProfile,
    serverAddress: connectedProfile.baseUrl.value,
    email: '',
    access: 'ready',
    reason: 'no-session',
    profileWarnings: [],
    warning: { area: 'session', operation: 'restore', reason: 'network' },
  });
});

test('scan again clears a failed connection submission back to idle', async () => {
  const gateway = new FakeAppFlowGateway();
  gateway.connectResult = {
    outcome: 'failed',
    failure: { area: 'server', operation: 'connect', reason: 'network' },
  };
  const controller = new AppFlowController(gateway);
  await controller.start();
  await controller.connect('https://books.example.com', 'qr');

  controller.cancelPendingConnection();

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'connection-required',
    profileWarnings: [],
  });
});

test('foreground restore failure keeps authenticated data with a stale warning', async () => {
  const gateway = new FakeAppFlowGateway();
  const activeProfile = profile();
  const restoredSession = session();
  gateway.activeProfileResult = {
    outcome: 'loaded',
    profile: activeProfile,
    warnings: [],
  };
  gateway.recheckResult = {
    outcome: 'connected',
    profile: activeProfile,
    warnings: [],
  };
  gateway.restoreResult = {
    outcome: 'authenticated',
    session: restoredSession,
  };
  const controller = new AppFlowController(gateway);
  await controller.start();
  gateway.restoreResult = {
    outcome: 'failed',
    failure: { area: 'session', operation: 'restore', reason: 'network' },
  };

  await controller.restoreOnForeground();

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'authenticated',
    profile: activeProfile,
    session: restoredSession,
    freshness: 'stale',
    profileWarnings: [],
    warning: { area: 'session', operation: 'restore', reason: 'network' },
  });
});

test('confirmed missing session on foreground moves to signed out', async () => {
  const gateway = new FakeAppFlowGateway();
  const activeProfile = profile();
  gateway.activeProfileResult = {
    outcome: 'loaded',
    profile: activeProfile,
    warnings: [],
  };
  gateway.recheckResult = {
    outcome: 'connected',
    profile: activeProfile,
    warnings: [],
  };
  gateway.restoreResult = { outcome: 'authenticated', session: session() };
  const controller = new AppFlowController(gateway);
  await controller.start();
  gateway.restoreResult = { outcome: 'unauthenticated' };

  await controller.restoreOnForeground();

  assert.equal(controller.getSnapshot().phase, 'signed-out');
});

test('unified sign in connects and authenticates as one operation', async () => {
  const gateway = new FakeAppFlowGateway();
  const connectedProfile = profile(
    true,
    'https://new-books.example.com',
    'profile-2',
  );
  const delayedConnect = deferred<ConnectProfileResult>();
  const delayedLogin = deferred<LoginFlowResult>();
  gateway.connectDeferred = delayedConnect;
  gateway.loginDeferred = delayedLogin;
  const controller = new AppFlowController(gateway);
  await controller.start();

  const signIn = controller.signIn({
    serverAddress: 'https://new-books.example.com',
    email: 'reader@example.com',
    password: 'correct horse battery staple',
  });

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'connecting',
    intent: 'sign-in',
    candidate: 'https://new-books.example.com',
    source: 'manual',
    profile: null,
    serverAddress: 'https://new-books.example.com',
    email: 'reader@example.com',
    profileWarnings: [],
  });
  assert.deepEqual(gateway.connectCandidates, [
    'https://new-books.example.com',
  ]);
  assert.deepEqual(gateway.connectSources, ['manual']);

  delayedConnect.resolve({
    outcome: 'connected',
    profile: connectedProfile,
    warnings: [],
  });
  await Promise.resolve();

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'authenticating',
    profile: connectedProfile,
    serverAddress: 'https://new-books.example.com',
    email: 'reader@example.com',
    profileWarnings: [],
  });
  assert.strictEqual(
    gateway.connectCancellations[0],
    gateway.loginCancellations[0],
  );
  assert.deepEqual(gateway.loginProfiles, [connectedProfile]);
  assert.deepEqual(gateway.loginCredentials, {
    email: 'reader@example.com',
    password: 'correct horse battery staple',
  });

  const authenticatedSession = session('Unified sign in');
  delayedLogin.resolve({
    outcome: 'authenticated',
    session: authenticatedSession,
  });
  await signIn;

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'authenticated',
    profile: connectedProfile,
    session: authenticatedSession,
    freshness: 'fresh',
    profileWarnings: [],
  });
});

test('unified sign in connection failure retains the previous profile', async () => {
  const gateway = new FakeAppFlowGateway();
  const previousProfile = profile();
  gateway.activeProfileResult = {
    outcome: 'loaded',
    profile: previousProfile,
    warnings: [],
  };
  gateway.recheckResult = {
    outcome: 'connected',
    profile: previousProfile,
    warnings: [],
  };
  gateway.restoreResult = { outcome: 'unauthenticated' };
  gateway.connectResult = {
    outcome: 'failed',
    failure: { area: 'server', operation: 'connect', reason: 'network' },
  };
  const controller = new AppFlowController(gateway);
  await controller.start();

  await controller.signIn({
    serverAddress: 'https://unreachable.example.com',
    email: 'reader@example.com',
    password: 'secret',
  });

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'signed-out',
    profile: previousProfile,
    serverAddress: 'https://unreachable.example.com',
    email: 'reader@example.com',
    access: 'ready',
    reason: 'no-session',
    profileWarnings: [],
    warning: { area: 'server', operation: 'connect', reason: 'network' },
  });
  assert.deepEqual(gateway.loginProfiles, []);
});

test('successful server switch retains the new profile when authentication is rejected', async () => {
  const gateway = new FakeAppFlowGateway();
  const previousProfile = profile();
  const connectedProfile = profile(
    true,
    'https://new-books.example.com',
    'profile-2',
  );
  gateway.activeProfileResult = {
    outcome: 'loaded',
    profile: previousProfile,
    warnings: [],
  };
  gateway.recheckResult = {
    outcome: 'connected',
    profile: previousProfile,
    warnings: [],
  };
  gateway.restoreResult = { outcome: 'unauthenticated' };
  gateway.connectResult = {
    outcome: 'connected',
    profile: connectedProfile,
    warnings: [{ kind: 'maintenance-cleanup-failed', issueCount: 1 }],
  };
  gateway.loginResult = { outcome: 'rejected', reason: 'invalid-credentials' };
  const controller = new AppFlowController(gateway);
  await controller.start();

  await controller.signIn({
    serverAddress: 'https://new-books.example.com',
    email: 'reader@example.com',
    password: 'incorrect',
  });

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'signed-out',
    profile: connectedProfile,
    serverAddress: 'https://new-books.example.com',
    email: 'reader@example.com',
    access: 'ready',
    reason: 'no-session',
    profileWarnings: [
      { kind: 'maintenance-cleanup-failed', issueCount: 1 },
    ],
    warning: {
      area: 'session',
      operation: 'login',
      reason: 'invalid-credentials',
    },
  });
  assert.deepEqual(gateway.loginProfiles, [connectedProfile]);
});

test('authentication transport failure retains the newly connected profile', async () => {
  const gateway = new FakeAppFlowGateway();
  const connectedProfile = profile(
    true,
    'https://new-books.example.com',
    'profile-2',
  );
  gateway.connectResult = {
    outcome: 'connected',
    profile: connectedProfile,
    warnings: [],
  };
  gateway.loginResult = {
    outcome: 'failed',
    failure: { area: 'session', operation: 'login', reason: 'network' },
  };
  const controller = new AppFlowController(gateway);
  await controller.start();

  await controller.signIn({
    serverAddress: 'https://new-books.example.com',
    email: 'reader@example.com',
    password: 'secret',
  });

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'signed-out',
    profile: connectedProfile,
    serverAddress: 'https://new-books.example.com',
    email: 'reader@example.com',
    access: 'ready',
    reason: 'no-session',
    profileWarnings: [],
    warning: { area: 'session', operation: 'login', reason: 'network' },
  });
});

test('cancelling unified sign in while connecting rejects both late stages', async () => {
  const gateway = new FakeAppFlowGateway();
  const delayedConnect = deferred<ConnectProfileResult>();
  gateway.connectDeferred = delayedConnect;
  const controller = new AppFlowController(gateway);
  await controller.start();

  const signIn = controller.signIn({
    serverAddress: 'https://new-books.example.com',
    email: 'reader@example.com',
    password: 'secret',
  });
  controller.cancelPendingLogin();

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'signed-out',
    profile: null,
    serverAddress: 'https://new-books.example.com',
    email: 'reader@example.com',
    access: 'ready',
    reason: 'no-session',
    profileWarnings: [],
  });
  assert.equal(
    gateway.connectCancellations[0]?.isCancellationRequested(),
    true,
  );

  delayedConnect.resolve({
    outcome: 'connected',
    profile: profile(true, 'https://new-books.example.com', 'profile-2'),
    warnings: [],
  });
  await signIn;

  assert.equal(controller.getSnapshot().phase, 'signed-out');
  assert.deepEqual(gateway.loginProfiles, []);
});

test('cancelling unified sign in while authenticating retains the new profile and ignores a late login', async () => {
  const gateway = new FakeAppFlowGateway();
  const connectedProfile = profile(
    true,
    'https://new-books.example.com',
    'profile-2',
  );
  const delayedLogin = deferred<LoginFlowResult>();
  gateway.connectResult = {
    outcome: 'connected',
    profile: connectedProfile,
    warnings: [],
  };
  gateway.loginDeferred = delayedLogin;
  const controller = new AppFlowController(gateway);
  await controller.start();

  const signIn = controller.signIn({
    serverAddress: 'https://new-books.example.com',
    email: 'reader@example.com',
    password: 'secret',
  });
  await Promise.resolve();
  assert.equal(controller.getSnapshot().phase, 'authenticating');
  assert.strictEqual(
    gateway.connectCancellations[0],
    gateway.loginCancellations[0],
  );

  controller.cancelPendingLogin();

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'signed-out',
    profile: connectedProfile,
    serverAddress: 'https://new-books.example.com',
    email: 'reader@example.com',
    access: 'ready',
    reason: 'no-session',
    profileWarnings: [],
  });
  assert.equal(
    gateway.loginCancellations[0]?.isCancellationRequested(),
    true,
  );

  delayedLogin.resolve({ outcome: 'authenticated', session: session() });
  await signIn;

  assert.equal(controller.getSnapshot().phase, 'signed-out');
});

test('setup-required login rejection forces setup access despite a stale initialized profile', async () => {
  const gateway = new FakeAppFlowGateway();
  const connectedProfile = profile(
    true,
    'https://new-books.example.com',
    'profile-2',
  );
  gateway.connectResult = {
    outcome: 'connected',
    profile: connectedProfile,
    warnings: [],
  };
  gateway.loginResult = { outcome: 'rejected', reason: 'setup-required' };
  const controller = new AppFlowController(gateway);
  await controller.start();

  await controller.signIn({
    serverAddress: 'https://new-books.example.com',
    email: 'reader@example.com',
    password: 'secret',
  });

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'signed-out',
    profile: connectedProfile,
    serverAddress: 'https://new-books.example.com',
    email: 'reader@example.com',
    access: 'setup-required',
    reason: 'server-setup-required',
    profileWarnings: [],
    warning: {
      area: 'session',
      operation: 'login',
      reason: 'setup-required',
    },
  });
});

test('logout stays authenticated when the server does not confirm it', async () => {
  const gateway = new FakeAppFlowGateway();
  const activeProfile = profile();
  gateway.activeProfileResult = {
    outcome: 'loaded',
    profile: activeProfile,
    warnings: [],
  };
  gateway.recheckResult = {
    outcome: 'connected',
    profile: activeProfile,
    warnings: [],
  };
  gateway.restoreResult = { outcome: 'authenticated', session: session() };
  gateway.logoutResult = {
    outcome: 'failed',
    failure: { area: 'session', operation: 'logout', reason: 'timeout' },
  };
  const controller = new AppFlowController(gateway);
  await controller.start();

  await controller.logout();

  const failedLogout = controller.getSnapshot();
  assert.equal(failedLogout.phase, 'authenticated');
  if (failedLogout.phase !== 'authenticated') return;
  assert.equal(failedLogout.freshness, 'stale');

  gateway.logoutResult = { outcome: 'logged-out' };
  await controller.logout();
  const confirmedLogout = controller.getSnapshot();
  assert.equal(confirmedLogout.phase, 'signed-out');
  if (confirmedLogout.phase !== 'signed-out') return;
  assert.equal(confirmedLogout.reason, 'logout-confirmed');
});

test('confirmed logout for connection management anchors that signed-out intent', async () => {
  const gateway = new FakeAppFlowGateway();
  const activeProfile = profile();
  gateway.activeProfileResult = {
    outcome: 'loaded',
    profile: activeProfile,
    warnings: [],
  };
  gateway.recheckResult = {
    outcome: 'connected',
    profile: activeProfile,
    warnings: [],
  };
  gateway.restoreResult = { outcome: 'authenticated', session: session() };
  const controller = new AppFlowController(gateway);
  await controller.start();

  await controller.logoutForConnectionManagement();

  const state = controller.getSnapshot();
  assert.equal(state.phase, 'signed-out');
  if (state.phase !== 'signed-out') return;
  assert.equal(state.reason, 'connection-management-requested');
  assert.strictEqual(state.profile, activeProfile);
});

test('failed connection-management logout preserves the authenticated session', async () => {
  const gateway = new FakeAppFlowGateway();
  const activeProfile = profile();
  const activeSession = session();
  gateway.activeProfileResult = {
    outcome: 'loaded',
    profile: activeProfile,
    warnings: [],
  };
  gateway.recheckResult = {
    outcome: 'connected',
    profile: activeProfile,
    warnings: [],
  };
  gateway.restoreResult = {
    outcome: 'authenticated',
    session: activeSession,
  };
  gateway.logoutResult = {
    outcome: 'failed',
    failure: { area: 'session', operation: 'logout', reason: 'network' },
  };
  const controller = new AppFlowController(gateway);
  await controller.start();

  await controller.logoutForConnectionManagement();

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'authenticated',
    profile: activeProfile,
    session: activeSession,
    freshness: 'stale',
    profileWarnings: [],
    warning: {
      area: 'session',
      operation: 'logout',
      reason: 'network',
    },
  });
});

test('session expiry cancels a pending logout and rejects its late result', async () => {
  const gateway = new FakeAppFlowGateway();
  const activeProfile = profile();
  gateway.activeProfileResult = {
    outcome: 'loaded',
    profile: activeProfile,
    warnings: [],
  };
  gateway.recheckResult = {
    outcome: 'connected',
    profile: activeProfile,
    warnings: [],
  };
  gateway.restoreResult = { outcome: 'authenticated', session: session() };
  const delayedLogout = deferred<LogoutFlowResult>();
  gateway.logoutDeferred = delayedLogout;
  const controller = new AppFlowController(gateway);
  await controller.start();

  const logout = controller.logout();
  assert.equal(controller.getSnapshot().phase, 'logging-out');
  controller.sessionExpired();
  delayedLogout.resolve({ outcome: 'logged-out' });
  await logout;

  const state = controller.getSnapshot();
  assert.equal(state.phase, 'signed-out');
  if (state.phase !== 'signed-out') return;
  assert.equal(state.reason, 'session-expired');
  assert.strictEqual(state.profile, activeProfile);
});

test('a newer connection cancels and supersedes cold-start results', async () => {
  const gateway = new FakeAppFlowGateway();
  const delayedProfile = deferred<ActiveProfileResult>();
  gateway.activeProfileDeferred = delayedProfile;
  gateway.connectResult = {
    outcome: 'connected',
    profile: profile(),
    warnings: [],
  };
  gateway.restoreResult = { outcome: 'authenticated', session: session('New') };
  const controller = new AppFlowController(gateway);
  const coldStart = controller.start();

  await controller.connect('https://books.example.com', 'manual');
  delayedProfile.resolve({ outcome: 'loaded', profile: null, warnings: [] });
  await coldStart;

  const state = controller.getSnapshot();
  assert.equal(state.phase, 'authenticated');
  if (state.phase !== 'authenticated') return;
  assert.equal(state.session.user.name, 'New');
});

test('selecting a stored profile restores its session through the selected profile', async () => {
  const gateway = new FakeAppFlowGateway();
  const selectedProfile = profile();
  gateway.recheckResult = {
    outcome: 'connected',
    profile: selectedProfile,
    warnings: [],
  };
  gateway.restoreResult = { outcome: 'authenticated', session: session() };
  const controller = new AppFlowController(gateway);
  await controller.start();

  await controller.selectProfile(selectedProfile.id);

  const state = controller.getSnapshot();
  assert.equal(state.phase, 'authenticated');
  if (state.phase !== 'authenticated') return;
  assert.equal(state.profile.id, selectedProfile.id);
});

test('removing the active profile cancels its flow and opens unified sign in', async () => {
  const gateway = new FakeAppFlowGateway();
  const activeProfile = profile();
  gateway.activeProfileResult = {
    outcome: 'loaded',
    profile: activeProfile,
    warnings: [],
  };
  gateway.recheckResult = {
    outcome: 'connected',
    profile: activeProfile,
    warnings: [],
  };
  gateway.restoreResult = { outcome: 'authenticated', session: session() };
  const controller = new AppFlowController(gateway);
  await controller.start();

  controller.profileRemoved(activeProfile.id);

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'signed-out',
    profile: null,
    serverAddress: '',
    email: '',
    access: 'ready',
    reason: 'no-session',
    profileWarnings: [],
  });
});

test('resetting profiles always returns to clean unified sign in', async () => {
  const gateway = new FakeAppFlowGateway();
  const controller = new AppFlowController(gateway);
  await controller.start();

  controller.profilesReset();

  assert.deepEqual(controller.getSnapshot(), {
    phase: 'signed-out',
    profile: null,
    serverAddress: '',
    email: '',
    access: 'ready',
    reason: 'no-session',
    profileWarnings: [],
  });
});

import type {
  IdentitySession,
  LoginResult,
  LogoutResult,
  RestoreSessionResult,
} from '../../identity/public';
import {
  type CancellationToken,
  type ConnectServer,
  type ConnectServerResult,
  type LoadServerProfiles,
  type LoadServerProfilesResult,
  type SelectServerProfile,
  type SelectServerProfileResult,
  type ServerProfile,
} from '../../server-connection/public';
import type {
  ActiveProfileResult,
  AppFlowGateway,
  ConnectProfileResult,
  LoginFlowResult,
  LogoutFlowResult,
  RestoreFlowSessionResult,
} from '../application/ports';
import type { AppFlowFailure } from '../model/app-flow-state';

export type AppFlowFeatureServices = Readonly<{
  connectServer: Pick<ConnectServer, 'execute'>;
  identitySession: Pick<
    IdentitySession,
    'login' | 'logout' | 'restoreSession'
  >;
  loadServerProfiles: Pick<LoadServerProfiles, 'execute'>;
  selectServerProfile: Pick<SelectServerProfile, 'execute'>;
}>;

function unexpectedFailure(
  area: AppFlowFailure['area'],
  operation: AppFlowFailure['operation'],
): AppFlowFailure {
  return { area, operation, reason: 'unexpected-failure' };
}

function connectionFailure(
  result: Exclude<ConnectServerResult, Readonly<{ outcome: 'connected' }>>,
): AppFlowFailure {
  switch (result.outcome) {
    case 'invalid-address':
      return { area: 'server', operation: 'connect', reason: result.code };
    case 'unreachable':
      return { area: 'server', operation: 'connect', reason: result.reason };
    case 'unhealthy':
      return { area: 'server', operation: 'connect', reason: result.status };
    case 'incompatible':
      return { area: 'server', operation: 'connect', reason: result.reason };
    case 'profile-save-failed':
      return { area: 'profile', operation: 'connect', reason: result.reason };
    case 'cancelled':
      return { area: 'server', operation: 'connect', reason: 'cancelled' };
  }
}

function loadFailure(
  result: Exclude<LoadServerProfilesResult, Readonly<{ outcome: 'loaded' }>>,
): AppFlowFailure {
  return {
    area: 'profile',
    operation: 'load-profile',
    reason: result.outcome === 'cancelled' ? 'cancelled' : result.reason,
  };
}

function selectionFailure(
  result: Exclude<SelectServerProfileResult, Readonly<{ outcome: 'selected' }>>,
): AppFlowFailure {
  switch (result.outcome) {
    case 'not-found':
      return { area: 'profile', operation: 'connect', reason: 'not-found' };
    case 'cancelled':
      return { area: 'server', operation: 'connect', reason: 'cancelled' };
    case 'unreachable':
      return { area: 'server', operation: 'connect', reason: result.reason };
    case 'unhealthy':
      return { area: 'server', operation: 'connect', reason: result.status };
    case 'incompatible':
      return { area: 'server', operation: 'connect', reason: result.reason };
    case 'failed':
      return { area: 'profile', operation: 'connect', reason: result.reason };
  }
}

function restoreResult(result: RestoreSessionResult): RestoreFlowSessionResult {
  if (result.outcome !== 'failure') return result;
  return {
    outcome: 'failed',
    failure: {
      area: 'session',
      operation: 'restore',
      reason: result.reason,
    },
  };
}

function loginResult(result: LoginResult): LoginFlowResult {
  if (result.outcome !== 'failure') return result;
  return {
    outcome: 'failed',
    failure: {
      area: 'session',
      operation: 'login',
      reason: result.reason,
    },
  };
}

function logoutResult(result: LogoutResult): LogoutFlowResult {
  if (result.outcome !== 'failure') return result;
  return {
    outcome: 'failed',
    failure: {
      area: 'session',
      operation: 'logout',
      reason: result.reason,
    },
  };
}

export class FeatureAppFlowGateway implements AppFlowGateway {
  constructor(private readonly services: AppFlowFeatureServices) {}

  async loadActiveProfile(
    cancellation: CancellationToken,
  ): Promise<ActiveProfileResult> {
    try {
      const result = await this.services.loadServerProfiles.execute(
        cancellation,
      );
      if (result.outcome !== 'loaded') {
        return { outcome: 'failed', failure: loadFailure(result) };
      }
      const activeProfile =
        result.catalog.activeProfileId === null
          ? null
          : (result.catalog.profiles.find(
              (profile) => profile.id === result.catalog.activeProfileId,
            ) ?? null);
      if (
        result.catalog.activeProfileId !== null &&
        activeProfile === null
      ) {
        return {
          outcome: 'failed',
          failure: {
            area: 'profile',
            operation: 'load-profile',
            reason: 'active-profile-missing',
          },
        };
      }
      return {
        outcome: 'loaded',
        profile: activeProfile,
        warnings: result.warnings,
      };
    } catch {
      return {
        outcome: 'failed',
        failure: unexpectedFailure('profile', 'load-profile'),
      };
    }
  }

  async recheckProfile(
    profile: ServerProfile,
    cancellation: CancellationToken,
  ): Promise<ConnectProfileResult> {
    return this.selectProfile(profile.id, cancellation);
  }

  async selectProfile(
    profileId: string,
    cancellation: CancellationToken,
  ): Promise<ConnectProfileResult> {
    try {
      const result = await this.services.selectServerProfile.execute(
        profileId,
        cancellation,
      );
      return result.outcome === 'selected'
        ? {
            outcome: 'connected',
            profile: result.profile,
            warnings: result.warnings,
          }
        : { outcome: 'failed', failure: selectionFailure(result) };
    } catch {
      return {
        outcome: 'failed',
        failure: unexpectedFailure('server', 'connect'),
      };
    }
  }

  async connect(
    candidate: string,
    source: 'manual' | 'qr',
    cancellation: CancellationToken,
  ): Promise<ConnectProfileResult> {
    try {
      const result = await this.services.connectServer.execute({
        candidate,
        source,
        cancellation,
      });
      return result.outcome === 'connected'
        ? {
            outcome: 'connected',
            profile: result.profile,
            warnings: result.warnings,
          }
        : { outcome: 'failed', failure: connectionFailure(result) };
    } catch {
      return {
        outcome: 'failed',
        failure: unexpectedFailure('server', 'connect'),
      };
    }
  }

  async restoreSession(
    profile: ServerProfile,
    cancellation: CancellationToken,
  ): Promise<RestoreFlowSessionResult> {
    try {
      return restoreResult(
        await this.services.identitySession.restoreSession(
          profile.baseUrl,
          cancellation,
        ),
      );
    } catch {
      return {
        outcome: 'failed',
        failure: unexpectedFailure('session', 'restore'),
      };
    }
  }

  async login(
    profile: ServerProfile,
    credentials: Readonly<{ email: string; password: string }>,
    cancellation: CancellationToken,
  ): Promise<LoginFlowResult> {
    try {
      return loginResult(
        await this.services.identitySession.login(
          profile.baseUrl,
          credentials,
          cancellation,
        ),
      );
    } catch {
      return {
        outcome: 'failed',
        failure: unexpectedFailure('session', 'login'),
      };
    }
  }

  async logout(
    profile: ServerProfile,
    cancellation: CancellationToken,
  ): Promise<LogoutFlowResult> {
    try {
      return logoutResult(
        await this.services.identitySession.logout(
          profile.baseUrl,
          cancellation,
        ),
      );
    } catch {
      return {
        outcome: 'failed',
        failure: unexpectedFailure('session', 'logout'),
      };
    }
  }
}

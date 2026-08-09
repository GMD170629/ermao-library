import type {
  CancellationToken,
  ServerProfileCatalog,
  ServerProfilePersistenceWarning,
} from '../../server-connection/public';
import type {
  AppFlowCancellationFactory,
  AppFlowCancellationSource,
} from './ports';

export type ServerProfilesFlowFailure = Readonly<{
  reason:
    | 'cancelled'
    | 'corrupt-local-data'
    | 'not-corrupt'
    | 'not-found'
    | 'storage-unavailable'
    | 'unexpected-failure';
}>;

export type ServerProfilesFlowState =
  | Readonly<{ phase: 'loading' }>
  | Readonly<{
      phase: 'ready';
      catalog: ServerProfileCatalog;
      warnings: readonly ServerProfilePersistenceWarning[];
      pending?: Readonly<{
        operation: 'delete' | 'select';
        profileId: string;
      }>;
    }>
  | Readonly<{
      phase: 'failed';
      failure: ServerProfilesFlowFailure;
      pendingReset: boolean;
    }>;

export type LoadProfilesFlowResult =
  | Readonly<{
      outcome: 'loaded';
      catalog: ServerProfileCatalog;
      warnings: readonly ServerProfilePersistenceWarning[];
    }>
  | Readonly<{
      outcome: 'failed';
      failure: ServerProfilesFlowFailure;
    }>;

export type DeleteProfileFlowResult =
  | Readonly<{
      outcome: 'deleted';
      catalog: ServerProfileCatalog;
      warnings: readonly ServerProfilePersistenceWarning[];
    }>
  | Readonly<{ outcome: 'not-found' }>
  | Readonly<{
      outcome: 'failed';
      failure: ServerProfilesFlowFailure;
    }>;

export type ResetProfilesFlowResult =
  | Readonly<{ outcome: 'reset' }>
  | Readonly<{ outcome: 'not-corrupt' }>
  | Readonly<{
      outcome: 'failed';
      failure: ServerProfilesFlowFailure;
    }>;

export interface ServerProfilesFlowGateway {
  load(cancellation: CancellationToken): Promise<LoadProfilesFlowResult>;
  delete(
    profileId: string,
    cancellation: CancellationToken,
  ): Promise<DeleteProfileFlowResult>;
  reset(cancellation: CancellationToken): Promise<ResetProfilesFlowResult>;
}

export type ServerProfilesFlowEvents = Readonly<{
  profileSelected(profileId: string): Promise<void>;
  profileRemoved(profileId: string): void;
  profilesReset(): void;
}>;

type Listener = () => void;

export class ServerProfilesController {
  private state: ServerProfilesFlowState = { phase: 'loading' };
  private readonly listeners = new Set<Listener>();
  private operationSequence = 0;
  private operation: Readonly<{
    sequence: number;
    cancellation: AppFlowCancellationSource;
  }> | null = null;

  constructor(
    private readonly gateway: ServerProfilesFlowGateway,
    private readonly events: ServerProfilesFlowEvents,
    private readonly cancellations: AppFlowCancellationFactory,
  ) {}

  readonly getSnapshot = (): ServerProfilesFlowState => this.state;

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  async load(): Promise<void> {
    const operation = this.beginOperation();
    this.publish({ phase: 'loading' });
    const result = await this.gateway.load(operation.cancellation.token);
    if (!this.isCurrent(operation)) return;
    this.publish(
      result.outcome === 'loaded'
        ? {
            phase: 'ready',
            catalog: result.catalog,
            warnings: result.warnings,
          }
        : {
            phase: 'failed',
            failure: result.failure,
            pendingReset: false,
          },
    );
  }

  async delete(profileId: string): Promise<void> {
    const current = this.state;
    if (current.phase !== 'ready') return;
    const operation = this.beginOperation();
    this.publish({
      ...current,
      pending: { operation: 'delete', profileId },
    });
    const result = await this.gateway.delete(
      profileId,
      operation.cancellation.token,
    );
    if (!this.isCurrent(operation)) return;
    if (result.outcome === 'deleted') {
      this.events.profileRemoved(profileId);
      this.publish({
        phase: 'ready',
        catalog: result.catalog,
        warnings: result.warnings,
      });
      return;
    }
    if (result.outcome === 'not-found') {
      this.events.profileRemoved(profileId);
      this.publish({
        phase: 'ready',
        catalog: {
          ...current.catalog,
          activeProfileId:
            current.catalog.activeProfileId === profileId
              ? null
              : current.catalog.activeProfileId,
          profiles: current.catalog.profiles.filter(
            (profile) => profile.id !== profileId,
          ),
        },
        warnings: current.warnings,
      });
      return;
    }
    this.publish({
      phase: 'failed',
      failure: result.failure,
      pendingReset: false,
    });
  }

  async select(profileId: string): Promise<void> {
    const current = this.state;
    if (current.phase !== 'ready') return;
    const operation = this.beginOperation();
    this.publish({
      ...current,
      pending: { operation: 'select', profileId },
    });
    await this.events.profileSelected(profileId);
    if (!this.isCurrent(operation)) return;
    this.publish(current);
  }

  async resetCorrupt(): Promise<void> {
    const previous = this.state;
    if (previous.phase !== 'failed') return;
    const operation = this.beginOperation();
    this.publish({ ...previous, pendingReset: true });
    const result = await this.gateway.reset(operation.cancellation.token);
    if (!this.isCurrent(operation)) return;
    if (result.outcome === 'reset') {
      this.events.profilesReset();
      this.publish({
        phase: 'ready',
        catalog: {
          generation: 0,
          activeProfileId: null,
          profiles: [],
          updatedAtMs: 0,
        },
        warnings: [],
      });
      return;
    }
    this.publish({
      phase: 'failed',
      failure:
        result.outcome === 'not-corrupt'
          ? { reason: 'not-corrupt' }
          : result.failure,
      pendingReset: false,
    });
  }

  dispose(): void {
    this.operationSequence += 1;
    this.operation?.cancellation.cancel();
    this.operation = null;
  }

  private beginOperation(): NonNullable<ServerProfilesController['operation']> {
    this.operation?.cancellation.cancel();
    const operation = {
      sequence: this.operationSequence + 1,
      cancellation: this.cancellations.create(),
    };
    this.operationSequence = operation.sequence;
    this.operation = operation;
    return operation;
  }

  private isCurrent(
    operation: NonNullable<ServerProfilesController['operation']>,
  ): boolean {
    return (
      this.operation === operation &&
      this.operationSequence === operation.sequence
    );
  }

  private publish(state: ServerProfilesFlowState): void {
    this.state = state;
    this.listeners.forEach((listener) => listener());
  }
}

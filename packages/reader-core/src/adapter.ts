import type {
  OperationToken,
  ReaderAdapterEvent,
  ReaderCapabilities,
  ReaderCommand,
  ReaderCommandAck,
  ReaderLocation,
  ReaderPositionReport,
  ReaderPreferences,
  ReaderSource
} from './types';

export type ReaderAdapterOperationContext = {
  operation: OperationToken;
  signal: AbortSignal;
};

export type ReaderAdapterOpenContext = ReaderAdapterOperationContext & {
  sessionId: string;
  source: ReaderSource;
  initialLocation: ReaderLocation | null;
  /** v5 restores only the engine-owned Locator; presentation is never a target. */
  initialPosition?: ReaderPositionReport | null;
  preferences: ReaderPreferences;
};

export type ReaderAdapterListener = (event: ReaderAdapterEvent) => void;

/** The DOM host belongs to each concrete adapter constructor, not this pure contract. */
export interface ReaderAdapter {
  open(context: ReaderAdapterOpenContext): Promise<void>;
  getCapabilities(): ReaderCapabilities;
  execute(command: ReaderCommand, context: ReaderAdapterOperationContext): Promise<ReaderCommandAck>;
  applyPreferences(preferences: ReaderPreferences, context: ReaderAdapterOperationContext): Promise<ReaderCommandAck>;
  subscribe(listener: ReaderAdapterListener): () => void;
  dispose(): Promise<void> | void;
}

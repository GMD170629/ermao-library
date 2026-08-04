import type {
  OperationToken,
  ReaderAdapterEvent,
  ReaderCapabilities,
  ReaderError,
  ReaderKind,
  ReaderLifecycle,
  ReaderLocation,
  ReaderNavigationEntry,
  ReaderOperationKind,
  ReaderPreferences
} from './types';

export type ReaderOperationVersions = Record<ReaderOperationKind, number>;

export type ReaderSessionState = {
  sessionId: string;
  lifecycle: ReaderLifecycle;
  kind: ReaderKind | null;
  preferences: ReaderPreferences;
  operations: ReaderOperationVersions;
  capabilities: ReaderCapabilities | null;
  totalPages: number | null;
  navigationItems: ReaderNavigationEntry[];
  navigationReady: boolean;
  location: ReaderLocation | null;
  percent: number;
  phase: string | null;
  downloadProgress: { loadedBytes: number; totalBytes: number | null; percent: number | null } | null;
  paginationProgress: { completed: number; total: number; percent: number } | null;
  error: ReaderError | null;
};

export type ReaderSessionAction =
  | { type: 'operation/begin'; operation: OperationToken }
  | { type: 'operation/complete'; operation: OperationToken }
  | { type: 'preferences/replace'; operation: OperationToken; preferences: ReaderPreferences }
  | { type: 'adapter/event'; event: ReaderAdapterEvent }
  | { type: 'session/fail'; operation: OperationToken; error: ReaderError }
  | { type: 'session/dispose' };

const INITIAL_OPERATIONS: ReaderOperationVersions = {
  bootstrap: 0,
  navigation: 0,
  render: 0,
  preferences: 0,
  pagination: 0
};

/*
 *                         operation token matches
 * bootstrapping -> loading -----------------------> ready
 *        |            |                              |
 *        |            +---------- error <------------+
 *        |                         |
 *        +-------------------------+-----> disposed
 *
 * sessionId + per-operation sequence is the only admission gate. An event from
 * an old adapter or an aborted operation cannot mutate the current session.
 */
export function createReaderSessionState(sessionId: string, preferences: ReaderPreferences, kind: ReaderKind | null = null): ReaderSessionState {
  return {
    sessionId,
    lifecycle: 'bootstrapping',
    kind,
    preferences,
    operations: { ...INITIAL_OPERATIONS },
    capabilities: null,
    totalPages: null,
    navigationItems: [],
    navigationReady: false,
    location: null,
    percent: 0,
    phase: null,
    downloadProgress: null,
    paginationProgress: null,
    error: null
  };
}

export function nextOperationToken(state: ReaderSessionState, kind: ReaderOperationKind): OperationToken {
  return { sessionId: state.sessionId, kind, sequence: state.operations[kind] + 1 };
}

export function isCurrentOperation(state: ReaderSessionState, operation: OperationToken): boolean {
  return state.lifecycle !== 'disposed'
    && operation.sessionId === state.sessionId
    && operation.sequence === state.operations[operation.kind];
}

function clampPercent(value: number) {
  return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
}

export function readerSessionReducer(state: ReaderSessionState, action: ReaderSessionAction): ReaderSessionState {
  if (state.lifecycle === 'disposed') return state;

  switch (action.type) {
    case 'operation/begin': {
      const { operation } = action;
      if (operation.sessionId !== state.sessionId || operation.sequence <= state.operations[operation.kind]) return state;
      return {
        ...state,
        lifecycle: operation.kind === 'bootstrap' ? 'loading' : state.lifecycle,
        error: operation.kind === 'bootstrap' ? null : state.error,
        downloadProgress: operation.kind === 'bootstrap' ? null : state.downloadProgress,
        paginationProgress: operation.kind === 'bootstrap' ? null : state.paginationProgress,
        operations: { ...state.operations, [operation.kind]: operation.sequence }
      };
    }
    case 'operation/complete':
      return isCurrentOperation(state, action.operation) ? state : state;
    case 'preferences/replace':
      return isCurrentOperation(state, action.operation) ? { ...state, preferences: action.preferences } : state;
    case 'session/fail':
      return isCurrentOperation(state, action.operation)
        ? { ...state, lifecycle: 'error', error: action.error, phase: null, downloadProgress: null, paginationProgress: null }
        : state;
    case 'adapter/event': {
      const { event } = action;
      if (event.sessionId !== state.sessionId || !isCurrentOperation(state, event.operation)) return state;
      switch (event.type) {
        case 'ready':
          return { ...state, lifecycle: 'ready', capabilities: event.capabilities, location: event.location, error: null, phase: null, downloadProgress: null, paginationProgress: null };
        case 'capabilities-changed':
          return { ...state, capabilities: event.capabilities };
        case 'metadata-changed':
          return { ...state, totalPages: event.totalPages };
        case 'navigation-changed':
          return { ...state, navigationItems: event.items, navigationReady: true };
        case 'location-changed':
          return { ...state, location: event.location, percent: clampPercent(event.percent) };
        case 'phase-changed':
          return {
            ...state,
            phase: event.phase,
            downloadProgress: event.phase === 'downloading-content' ? state.downloadProgress : null,
            paginationProgress: event.phase === 'generating-pagination' ? state.paginationProgress : null
          };
        case 'download-progress':
          return {
            ...state,
            downloadProgress: {
              loadedBytes: Math.max(0, Math.round(event.loadedBytes)),
              totalBytes: event.totalBytes === null ? null : Math.max(0, Math.round(event.totalBytes)),
              percent: event.percent === null ? null : clampPercent(event.percent)
            }
          };
        case 'pagination-progress':
          return {
            ...state,
            paginationProgress: {
              completed: Math.max(0, Math.round(event.completed)),
              total: Math.max(0, Math.round(event.total)),
              percent: clampPercent(event.percent)
            }
          };
        case 'error':
          return { ...state, lifecycle: 'error', error: event.error, phase: null, downloadProgress: null, paginationProgress: null };
        default:
          return state;
      }
    }
    case 'session/dispose':
      return { ...state, lifecycle: 'disposed', capabilities: null, totalPages: null, navigationItems: [], navigationReady: false, phase: null, downloadProgress: null, paginationProgress: null };
  }
}

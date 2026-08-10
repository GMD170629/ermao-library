export type ConnectionAddressIssue =
  | 'CREDENTIALS_NOT_ALLOWED'
  | 'DEVICE_LOOPBACK_NOT_ALLOWED'
  | 'EMPTY'
  | 'INSECURE_REMOTE_NOT_ALLOWED'
  | 'INVALID'
  | 'QUERY_OR_FRAGMENT_NOT_ALLOWED'
  | 'UNSUPPORTED_SCHEME';

export type ConnectionIssue =
  | ConnectionAddressIssue
  | 'cancelled'
  | 'capacity'
  | 'conflict'
  | 'corrupt-storage'
  | 'incompatible'
  | 'network'
  | 'storage-unavailable'
  | 'timeout'
  | 'unhealthy'
  | 'unknown';

export type ConnectionSubmissionState =
  | Readonly<{ status: 'idle' }>
  | Readonly<{ status: 'connecting' }>
  | Readonly<{ issue: ConnectionIssue; status: 'failed' }>;

export type ConnectionHomeScreenProps = Readonly<{
  activeServerUrl?: string;
  mode: 'needs-connection' | 'signed-out';
  onEnterAddress: () => void;
  onManageProfiles?: () => void;
  onScanQr: () => void;
}>;

export type ServerAddressScreenProps = Readonly<{
  initialAddress?: string;
  onAddressChange?: (address: string) => void;
  onCancel: () => void;
  onConnect: (address: string) => void;
  onScanQr: () => void;
  state: ConnectionSubmissionState;
}>;

export type ServerProfileSummary = Readonly<{
  active: boolean;
  basePath: string;
  baseUrl: string;
  id: string;
  initialized: boolean;
  lastVerifiedAtMs: number;
}>;

export type ServerProfilePendingAction = Readonly<{
  profileId: string;
  type: 'delete' | 'select';
}>;

export type ServerProfilesFailedPendingAction = Readonly<{
  type: 'reset';
}>;

export type ServerProfilesWarning =
  | 'maintenance-cleanup-failed'
  | 'recovered-older-snapshot';

export type ServerProfilesViewState =
  | Readonly<{ status: 'loading' }>
  | Readonly<{
      issue: ConnectionIssue;
      pendingAction?: ServerProfilesFailedPendingAction;
      status: 'failed';
    }>
  | Readonly<{
      pendingAction?: ServerProfilePendingAction;
      profiles: readonly ServerProfileSummary[];
      status: 'ready';
      warnings?: readonly ServerProfilesWarning[];
    }>;

type ServerProfilesScreenBaseProps = Readonly<{
  onRetry: () => void;
  state: ServerProfilesViewState;
}>;

export type ServerProfilesScreenProps = ServerProfilesScreenBaseProps &
  (
    | Readonly<{ mode: 'read-only' }>
    | Readonly<{
        mode: 'editable';
        onAddAddress: () => void;
        onAddQr: () => void;
        onDelete: (profileId: string) => void;
        onResetCorrupt: () => void;
        onSelect: (profileId: string) => void;
      }>
  );

export type QrScannerScreenProps = Readonly<{
  onCodeAccepted: (text: string) => void;
  onOpenSettings?: () => Promise<void>;
  onScanAgain: () => void;
  state: ConnectionSubmissionState;
}>;

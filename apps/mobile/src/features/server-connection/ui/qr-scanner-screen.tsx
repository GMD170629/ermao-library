import {
  CameraView,
  useCameraPermissions,
  type BarcodeScanningResult,
} from 'expo-camera';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { AppState, Linking, StyleSheet, View } from 'react-native';

import { useI18n, type MessageKey } from '../../../shared/i18n/public';
import {
  AppButton,
  AppIcon,
  AppText,
  InlineNotice,
  LoadingState,
  PageIntro,
  ScreenScaffold,
  useAppTheme,
} from '../../../shared/ui/public';
import { connectionIssueMessageKey } from './connection-issue';
import type { QrScannerScreenProps } from './contracts';
import {
  QrPayloadGate,
  type QrPayloadRejectionReason,
} from './qr-payload';

type ScannerState =
  | Readonly<{ status: 'scanning' }>
  | Readonly<{ status: 'submitted' }>
  | Readonly<{
      reason: QrPayloadRejectionReason;
      status: 'invalid';
    }>
  | Readonly<{ status: 'camera-failure' }>;

const rejectionMessageKeys: Readonly<
  Record<QrPayloadRejectionReason, MessageKey>
> = {
  'control-characters': 'connection.qr.invalidControlCharacters',
  empty: 'connection.qr.invalidEmpty',
  'too-long': 'connection.qr.invalidTooLong',
};

export function QrScannerScreen({
  onCodeAccepted,
  onOpenSettings = Linking.openSettings,
  onScanAgain,
  state,
}: QrScannerScreenProps): ReactNode {
  const { t } = useI18n();
  const theme = useAppTheme();
  const [permission, requestPermission] = useCameraPermissions();
  const [foreground, setForeground] = useState(
    AppState.currentState === 'active',
  );
  const [permissionFailure, setPermissionFailure] = useState(false);
  const [scannerState, setScannerState] = useState<ScannerState>({
    status: 'scanning',
  });
  const [cameraGeneration, setCameraGeneration] = useState(0);
  const gateRef = useRef(new QrPayloadGate());
  const mountedRef = useRef(false);
  const foregroundRef = useRef(foreground);

  useEffect(() => {
    const gate = gateRef.current;
    mountedRef.current = true;
    const subscription = AppState.addEventListener('change', (nextState) => {
      const nextForeground = nextState === 'active';
      foregroundRef.current = nextForeground;
      if (mountedRef.current) {
        setForeground(nextForeground);
      }
    });
    return () => {
      mountedRef.current = false;
      foregroundRef.current = false;
      gate.lock();
      subscription.remove();
    };
  }, []);

  function handleBarcodeScanned(result: BarcodeScanningResult): void {
    if (!mountedRef.current || !foregroundRef.current) {
      return;
    }
    const consumed = gateRef.current.consume(result.data);
    if (consumed.status === 'locked') {
      return;
    }
    if (consumed.status === 'rejected') {
      setScannerState({
        status: 'invalid',
        reason: consumed.reason,
      });
      return;
    }
    setScannerState({ status: 'submitted' });
    onCodeAccepted(consumed.value);
  }

  function scanAgain(): void {
    gateRef.current.reset();
    setScannerState({ status: 'scanning' });
    setCameraGeneration((generation) => generation + 1);
    onScanAgain();
  }

  async function askForPermission(): Promise<void> {
    setPermissionFailure(false);
    try {
      await requestPermission();
    } catch {
      if (mountedRef.current) {
        setPermissionFailure(true);
      }
    }
  }

  async function openSettings(): Promise<void> {
    setPermissionFailure(false);
    try {
      await onOpenSettings();
    } catch {
      if (mountedRef.current) {
        setPermissionFailure(true);
      }
    }
  }

  let scannerContent: ReactNode;
  if (permission === null) {
    scannerContent = (
      <LoadingState label={t('connection.qr.permissionLoading')} />
    );
  } else if (!permission.granted) {
    scannerContent = (
      <View style={styles.statePanel}>
        <View
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
          style={[
            styles.stateIcon,
            { backgroundColor: theme.colors.warningMuted },
          ]}
        >
          <AppIcon color={theme.colors.warning} decorative name="camera" />
        </View>
        <InlineNotice
          body={
            permission.canAskAgain
              ? t('connection.qr.permissionBody')
              : t('connection.qr.permissionDeniedBody')
          }
          title={
            permission.canAskAgain
              ? t('connection.qr.permissionTitle')
              : t('connection.qr.permissionDeniedTitle')
          }
          tone="warning"
        />
        {permissionFailure ? (
          <InlineNotice
            body={t('connection.qr.permissionFailure')}
            tone="danger"
          />
        ) : null}
        <AppButton
          accessibilityHint={
            permission.canAskAgain
              ? t('connection.qr.requestPermissionHint')
              : t('connection.qr.openSettingsHint')
          }
          fullWidth
          iconName={permission.canAskAgain ? 'camera' : 'settings'}
          label={
            permission.canAskAgain
              ? t('connection.qr.requestPermission')
              : t('common.openSettings')
          }
          onPress={() => {
            if (permission.canAskAgain) {
              void askForPermission();
            } else {
              void openSettings();
            }
          }}
          testID={
            permission.canAskAgain
              ? 'request-camera-permission'
              : 'open-camera-settings'
          }
        />
      </View>
    );
  } else if (!foreground) {
    scannerContent = (
      <View style={styles.statePanel}>
        <LoadingState label={t('connection.qr.paused')} />
      </View>
    );
  } else {
    scannerContent = (
      <View style={styles.scannerSection}>
        <View
          accessible
          accessibilityLabel={t('connection.qr.frameLabel')}
          accessibilityRole="image"
          style={[
            styles.cameraFrame,
            { backgroundColor: theme.colors.cardStrong },
          ]}
          testID="qr-scanner-frame"
        >
          {scannerState.status === 'camera-failure' ? null : (
            <CameraView
              barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
              facing="back"
              key={cameraGeneration}
              onMountError={() => {
                gateRef.current.lock();
                if (mountedRef.current) {
                  setScannerState({ status: 'camera-failure' });
                }
              }}
              style={StyleSheet.absoluteFill}
              {...(scannerState.status === 'scanning' &&
              state.status === 'idle'
                ? { onBarcodeScanned: handleBarcodeScanned }
                : {})}
            />
          )}
          <View
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            pointerEvents="none"
            style={[
              styles.frameOverlay,
              { backgroundColor: theme.colors.overlay },
            ]}
          >
            <View
              style={[
                styles.scanWindow,
                { borderColor: theme.colors.cardStrong },
              ]}
            />
          </View>
        </View>

        {state.status === 'idle' && scannerState.status === 'scanning' ? (
          <View
            accessibilityLiveRegion="polite"
            style={[
              styles.scanningStatus,
              {
                backgroundColor: theme.colors.card,
                borderColor: theme.colors.border,
              },
            ]}
          >
            <AppIcon
              color={theme.colors.tint}
              decorative
              name="scan"
              size={20}
            />
            <AppText muted style={styles.statusCopy}>
              {t('connection.qr.scanning')}
            </AppText>
          </View>
        ) : null}
        {state.status === 'connecting' ? (
          <LoadingState label={t('connection.qr.processing')} />
        ) : null}
        {state.status === 'failed' ? (
          <View style={styles.feedback}>
            <InlineNotice
              body={t(connectionIssueMessageKey(state.issue))}
              title={t('connection.issue.title')}
              tone="danger"
            />
            <AppButton
              accessibilityHint={t('connection.qr.scanAgainHint')}
              fullWidth
              iconName="scan"
              label={t('connection.qr.scanAgain')}
              onPress={scanAgain}
              testID="scan-qr-again"
            />
          </View>
        ) : null}
        {state.status === 'idle' && scannerState.status === 'submitted' ? (
          <View style={styles.feedback}>
            <InlineNotice
              body={t('connection.qr.submittedBody')}
              title={t('connection.qr.submittedTitle')}
            />
            <AppButton
              accessibilityHint={t('connection.qr.scanAgainHint')}
              fullWidth
              iconName="scan"
              label={t('connection.qr.scanAgain')}
              onPress={scanAgain}
              testID="scan-qr-again"
              variant="secondary"
            />
          </View>
        ) : null}
        {state.status === 'idle' && scannerState.status === 'invalid' ? (
          <View style={styles.feedback}>
            <InlineNotice
              body={t(rejectionMessageKeys[scannerState.reason])}
              title={t('connection.qr.invalidTitle')}
              tone="danger"
            />
            <AppButton
              accessibilityHint={t('connection.qr.scanAgainHint')}
              fullWidth
              iconName="scan"
              label={t('connection.qr.scanAgain')}
              onPress={scanAgain}
              testID="scan-qr-again"
            />
          </View>
        ) : null}
        {state.status === 'idle' &&
        scannerState.status === 'camera-failure' ? (
          <View style={styles.feedback}>
            <InlineNotice
              body={t('connection.qr.cameraFailure')}
              tone="danger"
            />
            <AppButton
              fullWidth
              iconName="refresh"
              label={t('common.retry')}
              onPress={scanAgain}
              testID="retry-camera"
            />
          </View>
        ) : null}
      </View>
    );
  }

  return (
    <ScreenScaffold contentStyle={styles.screen} testID="qr-scanner-screen">
      <PageIntro
        description={t('connection.qr.description')}
        eyebrow={t('connection.qr.eyebrow')}
      />
      {scannerContent}
    </ScreenScaffold>
  );
}

const styles = StyleSheet.create({
  cameraFrame: {
    alignSelf: 'center',
    aspectRatio: 1,
    borderRadius: 20,
    maxWidth: 520,
    overflow: 'hidden',
    width: '100%',
  },
  feedback: {
    alignSelf: 'center',
    gap: 12,
    maxWidth: 520,
    width: '100%',
  },
  frameOverlay: {
    alignItems: 'center',
    bottom: 0,
    justifyContent: 'center',
    left: 0,
    position: 'absolute',
    right: 0,
    top: 0,
  },
  scannerSection: {
    gap: 16,
  },
  scanningStatus: {
    alignItems: 'center',
    alignSelf: 'center',
    borderRadius: 14,
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
    gap: 8,
    minHeight: 48,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  scanWindow: {
    aspectRatio: 1,
    borderRadius: 20,
    borderWidth: 3,
    width: '70%',
  },
  screen: {
    gap: 24,
  },
  stateIcon: {
    alignItems: 'center',
    alignSelf: 'center',
    borderRadius: 20,
    height: 64,
    justifyContent: 'center',
    width: 64,
  },
  statePanel: {
    alignSelf: 'center',
    gap: 16,
    maxWidth: 560,
    width: '100%',
  },
  statusCopy: {
    flexShrink: 1,
  },
});

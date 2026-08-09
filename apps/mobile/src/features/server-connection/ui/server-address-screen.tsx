import { useState, type ReactNode } from 'react';
import { StyleSheet, useWindowDimensions, View } from 'react-native';

import { useI18n } from '../../../shared/i18n/public';
import {
  AppButton,
  AppIcon,
  AppTextField,
  InlineNotice,
  PageHeader,
  ScreenScaffold,
  useAppTheme,
} from '../../../shared/ui/public';
import { connectionIssueMessageKey } from './connection-issue';
import type {
  ConnectionAddressIssue,
  ConnectionIssue,
  ServerAddressScreenProps,
} from './contracts';

const MAXIMUM_ADDRESS_LENGTH = 2_048;

export function ServerAddressScreen({
  initialAddress = '',
  onAddressChange,
  onBack,
  onCancel,
  onConnect,
  onScanQr,
  state,
}: ServerAddressScreenProps): ReactNode {
  const { t } = useI18n();
  const theme = useAppTheme();
  const { fontScale, width } = useWindowDimensions();
  const [address, setAddress] = useState(initialAddress);
  const connecting = state.status === 'connecting';
  const compactActions =
    width < theme.breakpoint.expandedMinWidth || fontScale > 1.3;
  const addressIssue =
    state.status === 'failed' && isAddressIssue(state.issue)
      ? state.issue
      : undefined;
  const connectionIssue =
    state.status === 'failed' && addressIssue === undefined
      ? state.issue
      : undefined;

  function updateAddress(value: string): void {
    setAddress(value);
    onAddressChange?.(value);
  }

  function submit(): void {
    if (!connecting) {
      onConnect(address.trim());
    }
  }

  return (
    <ScreenScaffold contentStyle={styles.screen} testID="server-address-screen">
      <PageHeader
        backAccessibilityHint={t('common.back')}
        backLabel={t('common.back')}
        description={t('connection.address.description')}
        eyebrow={t('connection.address.eyebrow')}
        onBack={onBack}
        title={t('connection.address.title')}
      />

      <View style={styles.form}>
        <AppTextField
          autoCapitalize="none"
          autoComplete="url"
          autoCorrect={false}
          disabled={connecting}
          {...(addressIssue === undefined
            ? {}
            : { error: t(connectionIssueMessageKey(addressIssue)) })}
          hint={t('connection.address.help')}
          keyboardType="url"
          label={t('connection.address.label')}
          leadingIconName="link"
          maxLength={MAXIMUM_ADDRESS_LENGTH}
          onChangeText={updateAddress}
          onSubmitEditing={submit}
          placeholder={t('connection.address.placeholder')}
          returnKeyType="go"
          testID="server-address-input"
          textContentType="URL"
          value={address}
        />

        {connectionIssue === undefined ? null : (
          <InlineNotice
            body={t(connectionIssueMessageKey(connectionIssue))}
            title={t('connection.issue.title')}
            tone={connectionIssue === 'cancelled' ? 'info' : 'danger'}
          />
        )}

        <View
          style={[
            styles.actions,
            !compactActions && styles.actionsExpanded,
          ]}
        >
          <AppButton
            fullWidth={compactActions}
            label={
              connecting
                ? t('connection.address.connecting')
                : t('connection.address.connect')
            }
            leadingIcon={
              <AppIcon
                color={theme.colors.onAction}
                decorative
                name="link"
              />
            }
            loading={connecting}
            onPress={submit}
            style={!compactActions && styles.actionExpanded}
            testID="connect-server"
          />
          {connecting ? (
            <AppButton
              accessibilityHint={t('connection.address.cancelHint')}
              fullWidth={compactActions}
              label={t('common.cancel')}
              onPress={onCancel}
              style={!compactActions && styles.actionExpanded}
              testID="cancel-server-connection"
              variant="secondary"
            />
          ) : (
            <AppButton
              accessibilityHint={t('connection.address.scanHint')}
              fullWidth={compactActions}
              label={t('connection.address.scanInstead')}
              leadingIcon={
                <AppIcon
                  color={theme.colors.tint}
                  decorative
                  name="scan"
                />
              }
              onPress={onScanQr}
              style={!compactActions && styles.actionExpanded}
              testID="scan-server-qr"
              variant="ghost"
            />
          )}
        </View>
      </View>
    </ScreenScaffold>
  );
}

function isAddressIssue(issue: ConnectionIssue): issue is ConnectionAddressIssue {
  switch (issue) {
    case 'CREDENTIALS_NOT_ALLOWED':
    case 'DEVICE_LOOPBACK_NOT_ALLOWED':
    case 'EMPTY':
    case 'INSECURE_REMOTE_NOT_ALLOWED':
    case 'INVALID':
    case 'QUERY_OR_FRAGMENT_NOT_ALLOWED':
    case 'UNSUPPORTED_SCHEME':
      return true;
    default:
      return false;
  }
}

const styles = StyleSheet.create({
  actionExpanded: {
    flex: 1,
  },
  actions: {
    gap: 8,
  },
  actionsExpanded: {
    flexDirection: 'row',
    gap: 12,
  },
  form: {
    gap: 20,
  },
  screen: {
    gap: 32,
  },
});

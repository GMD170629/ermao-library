import type { ReactNode } from 'react';
import {
  Alert,
  StyleSheet,
  useWindowDimensions,
  View,
} from 'react-native';

import { useI18n } from '../../../shared/i18n/public';
import {
  AppButton,
  AppIcon,
  AppText,
  InlineNotice,
  LoadingState,
  PageIntro,
  ScreenScaffold,
  SurfaceCard,
  SystemActionMenu,
  SystemListItem,
  useAppTheme,
} from '../../../shared/ui/public';
import {
  connectionIssueMessageKey,
  serverProfilesWarningMessageKey,
} from './connection-issue';
import type {
  ServerProfilePendingAction,
  ServerProfileSummary,
  ServerProfilesScreenProps,
} from './contracts';

export function ServerProfilesScreen(
  props: ServerProfilesScreenProps,
): ReactNode {
  const { t } = useI18n();
  const theme = useAppTheme();
  const { fontScale, width } = useWindowDimensions();
  const { mode, onRetry, state } = props;
  const editable = mode === 'editable';
  const expandedActions =
    width >= theme.breakpoint.expandedMinWidth && fontScale <= 1.3;
  const resetting =
    state.status === 'failed' && state.pendingAction?.type === 'reset';

  function confirmCorruptReset(): void {
    if (props.mode !== 'editable') {
      return;
    }
    Alert.alert(
      t('connection.profiles.resetCorruptTitle'),
      t('connection.profiles.resetCorruptMessage'),
      [
        { style: 'cancel', text: t('common.cancel') },
        {
          onPress: props.onResetCorrupt,
          style: 'destructive',
          text: t('connection.profiles.resetCorruptConfirm'),
        },
      ],
    );
  }

  return (
    <ScreenScaffold contentStyle={styles.screen} testID="server-profiles-screen">
      <PageIntro
        description={t(
          editable
            ? 'connection.profiles.description'
            : 'connection.profiles.readOnlyDescription',
        )}
        eyebrow={t(
          editable
            ? 'connection.profiles.eyebrow'
            : 'connection.profiles.readOnlyEyebrow',
        )}
      />

      {state.status === 'loading' ? (
        <LoadingState label={t('connection.profiles.loading')} />
      ) : null}

      {state.status === 'failed' ? (
        <View style={styles.stateSection}>
          <InlineNotice
            body={t(connectionIssueMessageKey(state.issue))}
            title={t('connection.profiles.loadFailure')}
            tone="danger"
          />
          <View
            style={[
              styles.actions,
              expandedActions && styles.actionsExpanded,
            ]}
          >
            <AppButton
              containerStyle={expandedActions && styles.actionExpanded}
              disabled={resetting}
              fullWidth={!expandedActions}
              iconName="refresh"
              label={t('common.retry')}
              onPress={onRetry}
              testID="retry-server-profiles"
              variant="secondary"
            />
            {editable && state.issue === 'corrupt-storage' ? (
              <AppButton
                accessibilityHint={t(
                  'connection.profiles.resetCorruptHint',
                )}
                containerStyle={expandedActions && styles.actionExpanded}
                fullWidth={!expandedActions}
                iconName="trash"
                label={
                  resetting
                    ? t('connection.profiles.resettingCorrupt')
                    : t('connection.profiles.resetCorruptAction')
                }
                loading={resetting}
                onPress={confirmCorruptReset}
                testID="reset-corrupt-server-profiles"
                variant="destructive"
              />
            ) : null}
          </View>
        </View>
      ) : null}

      {!editable && state.status === 'ready' ? (
        <View style={styles.stateSection}>
          <InlineNotice
            body={t('connection.profiles.readOnlyBody')}
            title={t('connection.profiles.readOnlyTitle')}
            tone="warning"
          />
          <AppButton
            accessibilityHint={t('connection.profiles.readOnlyRetryHint')}
            fullWidth
            iconName="refresh"
            label={t('connection.profiles.readOnlyRetry')}
            onPress={onRetry}
            testID="refresh-server-profile-recovery"
            variant="secondary"
          />
        </View>
      ) : null}

      {state.status === 'ready'
        ? state.warnings?.map((warning) => (
            <InlineNotice
              body={t(serverProfilesWarningMessageKey(warning))}
              key={warning}
              title={t('connection.profiles.warningTitle')}
              tone="warning"
            />
          ))
        : null}

      {state.status === 'ready' && state.profiles.length === 0 ? (
        <View style={styles.emptyState}>
          <View
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            style={[
              styles.emptyIcon,
              { backgroundColor: theme.colors.tintMuted },
            ]}
          >
            <AppIcon color={theme.colors.tint} decorative name="server" />
          </View>
          <View style={styles.emptyCopy}>
            <AppText accessibilityRole="header" variant="headline">
              {t('connection.profiles.emptyTitle')}
            </AppText>
            <AppText muted>
              {t(
                editable
                  ? 'connection.profiles.emptyBody'
                  : 'connection.profiles.emptyReadOnlyBody',
              )}
            </AppText>
          </View>
        </View>
      ) : null}

      {state.status === 'ready' && state.profiles.length > 0 ? (
        <SurfaceCard padding="none" style={styles.profileGroup}>
          {state.profiles.map((profile) => (
            <ServerProfileRow
              key={profile.id}
              {...(props.mode === 'editable'
                ? {
                    mode: props.mode,
                    onDelete: props.onDelete,
                    onSelect: props.onSelect,
                  }
                : { mode: props.mode })}
              {...(state.pendingAction === undefined
                ? {}
                : { pendingAction: state.pendingAction })}
              profile={profile}
            />
          ))}
        </SurfaceCard>
      ) : null}

      {state.status === 'ready' && props.mode === 'editable' ? (
        <View
          style={[
            styles.actions,
            expandedActions && styles.actionsExpanded,
          ]}
        >
          <AppButton
            accessibilityHint={t('connection.profiles.addManualHint')}
            containerStyle={expandedActions && styles.actionExpanded}
            fullWidth={!expandedActions}
            iconName="plus"
            label={t('connection.profiles.addManual')}
            onPress={props.onAddAddress}
            testID="add-server-address"
          />
          <AppButton
            accessibilityHint={t('connection.profiles.addQrHint')}
            containerStyle={expandedActions && styles.actionExpanded}
            fullWidth={!expandedActions}
            iconName="scan"
            label={t('connection.profiles.addQr')}
            onPress={props.onAddQr}
            testID="add-server-qr"
            variant="secondary"
          />
        </View>
      ) : null}
    </ScreenScaffold>
  );
}

type ServerProfileRowBaseProps = Readonly<{
  pendingAction?: ServerProfilePendingAction;
  profile: ServerProfileSummary;
}>;

type ServerProfileRowProps =
  | Readonly<ServerProfileRowBaseProps & { mode: 'read-only' }>
  | Readonly<
      ServerProfileRowBaseProps & {
        mode: 'editable';
        onDelete: (profileId: string) => void;
        onSelect: (profileId: string) => void;
      }
    >;

function ServerProfileRow(props: ServerProfileRowProps): ReactNode {
  const { pendingAction, profile } = props;
  const { formatDateTime, t } = useI18n();
  const selecting =
    pendingAction?.type === 'select' &&
    pendingAction.profileId === profile.id;
  const deleting =
    pendingAction?.type === 'delete' &&
    pendingAction.profileId === profile.id;
  const hasPendingAction = pendingAction !== undefined;
  const setupLabel = profile.initialized
    ? t('connection.profiles.ready')
    : t('connection.profiles.setupRequired');

  function confirmDelete(): void {
    if (props.mode !== 'editable') {
      return;
    }
    Alert.alert(
      t('connection.profiles.deleteTitle'),
      t('connection.profiles.deleteMessage', {
        server: profile.baseUrl,
      }),
      [
        { style: 'cancel', text: t('common.cancel') },
        {
          onPress: () => props.onDelete(profile.id),
          style: 'destructive',
          text: t('common.delete'),
        },
      ],
    );
  }

  return (
    <View
      style={styles.profileRow}
      testID={`server-profile-${profile.id}`}
    >
      <SystemListItem
        disabled={hasPendingAction}
        iconName="server"
        label={profile.baseUrl}
        selected={profile.active}
        supportingText={`${setupLabel} · ${profile.basePath} · ${formatDateTime(profile.lastVerifiedAtMs)}`}
        testID={`select-server-${profile.id}`}
        {...(props.mode === 'editable' && !profile.active
          ? { onPress: () => props.onSelect(profile.id) }
          : {})}
      />

      {props.mode === 'editable' ? (
        <View style={styles.profileMenu}>
          <SystemActionMenu
            accessibilityLabel={t('connection.profiles.title')}
            actions={[
              {
                disabled: profile.active || hasPendingAction,
                id: 'select',
                selected: profile.active,
                title: selecting
                  ? t('connection.profiles.selecting')
                  : profile.active
                    ? t('common.active')
                    : t('common.select'),
              },
              {
                destructive: true,
                disabled: hasPendingAction,
                id: 'delete',
                title: deleting
                  ? t('connection.profiles.deleting')
                  : t('common.delete'),
              },
            ]}
            onAction={(actionId) => {
              if (actionId === 'select') props.onSelect(profile.id);
              if (actionId === 'delete') confirmDelete();
            }}
            testID={`server-actions-${profile.id}`}
          />
        </View>
      ) : null}
    </View>
  );
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
  emptyCopy: {
    flex: 1,
    gap: 4,
  },
  emptyIcon: {
    alignItems: 'center',
    borderRadius: 20,
    height: 56,
    justifyContent: 'center',
    width: 56,
  },
  emptyState: {
    alignItems: 'flex-start',
    flexDirection: 'row',
    gap: 16,
    paddingVertical: 16,
  },
  profileGroup: {
    gap: 0,
    overflow: 'hidden',
  },
  profileMenu: {
    position: 'absolute',
    right: 4,
    top: 4,
  },
  profileRow: {
    paddingRight: 48,
    position: 'relative',
  },
  screen: {
    gap: 20,
  },
  stateSection: {
    gap: 12,
  },
});

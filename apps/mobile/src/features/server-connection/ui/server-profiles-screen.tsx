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
  PageHeader,
  ScreenScaffold,
  SurfaceCard,
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
  const { mode, onBack, onRetry, state } = props;
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
      <PageHeader
        backAccessibilityHint={t('common.back')}
        backLabel={t('common.back')}
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
        onBack={onBack}
        title={t('connection.profiles.title')}
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
              disabled={resetting}
              fullWidth={!expandedActions}
              label={t('common.retry')}
              leadingIcon={
                <AppIcon
                  color={theme.colors.text}
                  decorative
                  name="refresh"
                />
              }
              onPress={onRetry}
              style={expandedActions && styles.actionExpanded}
              testID="retry-server-profiles"
              variant="secondary"
            />
            {editable && state.issue === 'corrupt-storage' ? (
              <AppButton
                accessibilityHint={t(
                  'connection.profiles.resetCorruptHint',
                )}
                fullWidth={!expandedActions}
                label={
                  resetting
                    ? t('connection.profiles.resettingCorrupt')
                    : t('connection.profiles.resetCorruptAction')
                }
                leadingIcon={
                  <AppIcon
                    color={theme.colors.danger}
                    decorative
                    name="trash"
                  />
                }
                loading={resetting}
                onPress={confirmCorruptReset}
                style={expandedActions && styles.actionExpanded}
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
            label={t('connection.profiles.readOnlyRetry')}
            leadingIcon={
              <AppIcon
                color={theme.colors.text}
                decorative
                name="refresh"
              />
            }
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
          {state.profiles.map((profile, index) => (
            <ServerProfileRow
              divided={index > 0}
              expandedActions={expandedActions}
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
            fullWidth={!expandedActions}
            label={t('connection.profiles.addManual')}
            leadingIcon={
              <AppIcon
                color={theme.colors.onAction}
                decorative
                name="plus"
              />
            }
            onPress={props.onAddAddress}
            style={expandedActions && styles.actionExpanded}
            testID="add-server-address"
          />
          <AppButton
            accessibilityHint={t('connection.profiles.addQrHint')}
            fullWidth={!expandedActions}
            label={t('connection.profiles.addQr')}
            leadingIcon={
              <AppIcon
                color={theme.colors.text}
                decorative
                name="scan"
              />
            }
            onPress={props.onAddQr}
            style={expandedActions && styles.actionExpanded}
            testID="add-server-qr"
            variant="secondary"
          />
        </View>
      ) : null}
    </ScreenScaffold>
  );
}

type ServerProfileRowBaseProps = Readonly<{
  divided: boolean;
  expandedActions: boolean;
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
  const { divided, expandedActions, pendingAction, profile } = props;
  const { formatDateTime, t } = useI18n();
  const theme = useAppTheme();
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
      style={[
        styles.profileRow,
        divided && {
          borderTopColor: theme.colors.border,
          borderTopWidth: StyleSheet.hairlineWidth,
        },
        profile.active && { backgroundColor: theme.colors.tintMuted },
      ]}
      testID={`server-profile-${profile.id}`}
    >
      <View style={styles.profileHeading}>
        <View
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
          style={styles.profileIcon}
        >
          <AppIcon
            color={profile.active ? theme.colors.tint : theme.colors.textMuted}
            decorative
            name="server"
          />
        </View>
        <View style={styles.profileTitleCopy}>
          <AppText selectable variant="headline">
            {profile.baseUrl}
          </AppText>
          <AppText muted variant="caption">
            {setupLabel}
          </AppText>
        </View>
        {profile.active ? (
          <View style={styles.activeBadge}>
            <AppIcon
              color={theme.colors.tint}
              decorative
              name="check"
              size={16}
            />
            <AppText style={{ color: theme.colors.tint }} variant="caption">
              {t('common.active')}
            </AppText>
          </View>
        ) : null}
      </View>

      <View style={styles.metadata}>
        <View style={styles.metadataLine}>
          <AppText muted variant="caption">
            {t('connection.profiles.basePath')}
          </AppText>
          <AppText selectable style={styles.metadataValue} variant="caption">
            {profile.basePath}
          </AppText>
        </View>
        <View style={styles.metadataLine}>
          <AppText muted variant="caption">
            {t('connection.profiles.lastVerified')}
          </AppText>
          <AppText style={styles.metadataValue} variant="caption">
            {formatDateTime(profile.lastVerifiedAtMs)}
          </AppText>
        </View>
      </View>

      {props.mode === 'editable' ? (
        <View
          style={[
            styles.profileActions,
            expandedActions && styles.actionsExpanded,
          ]}
        >
          <AppButton
            accessibilityHint={t('connection.profiles.selectHint')}
            disabled={profile.active || hasPendingAction}
            fullWidth={!expandedActions}
            label={
              selecting
                ? t('connection.profiles.selecting')
                : profile.active
                  ? t('common.active')
                  : t('common.select')
            }
            leadingIcon={
              <AppIcon
                color={theme.colors.text}
                decorative
                name="check"
              />
            }
            loading={selecting}
            onPress={() => props.onSelect(profile.id)}
            style={expandedActions && styles.actionExpanded}
            testID={`select-server-${profile.id}`}
            variant="secondary"
          />
          <AppButton
            accessibilityHint={t('connection.profiles.deleteHint')}
            disabled={hasPendingAction}
            fullWidth={!expandedActions}
            label={
              deleting
                ? t('connection.profiles.deleting')
                : t('common.delete')
            }
            leadingIcon={
              <AppIcon
                color={theme.colors.danger}
                decorative
                name="trash"
              />
            }
            loading={deleting}
            onPress={confirmDelete}
            style={expandedActions && styles.actionExpanded}
            testID={`delete-server-${profile.id}`}
            variant="destructive"
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
  activeBadge: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 4,
    minHeight: 28,
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
  metadata: {
    gap: 4,
    paddingLeft: 40,
  },
  metadataLine: {
    alignItems: 'baseline',
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  metadataValue: {
    flexShrink: 1,
  },
  profileActions: {
    gap: 8,
    paddingLeft: 40,
  },
  profileGroup: {
    gap: 0,
    overflow: 'hidden',
  },
  profileHeading: {
    alignItems: 'flex-start',
    flexDirection: 'row',
    gap: 12,
  },
  profileIcon: {
    alignItems: 'center',
    height: 28,
    justifyContent: 'center',
    width: 28,
  },
  profileRow: {
    gap: 12,
    padding: 20,
  },
  profileTitleCopy: {
    flex: 1,
    gap: 2,
  },
  screen: {
    gap: 20,
  },
  stateSection: {
    gap: 12,
  },
});

import type { ReactNode } from 'react';
import {
  Pressable,
  StyleSheet,
  useWindowDimensions,
  View,
  type ViewStyle,
} from 'react-native';

import { useI18n } from '../../../shared/i18n/public';
import {
  AppButton,
  AppIcon,
  AppText,
  InlineNotice,
  PageHeader,
  ScreenScaffold,
  SurfaceCard,
  useAppTheme,
} from '../../../shared/ui/public';
import type { ConnectionHomeScreenProps } from './contracts';

export function ConnectionHomeScreen({
  activeServerUrl,
  mode,
  onEnterAddress,
  onManageProfiles,
  onScanQr,
}: ConnectionHomeScreenProps): ReactNode {
  const { t } = useI18n();
  const theme = useAppTheme();
  const { fontScale, width } = useWindowDimensions();
  const expanded =
    width >= theme.breakpoint.expandedMinWidth && fontScale <= 1.3;

  return (
    <ScreenScaffold contentStyle={styles.screen} testID="connection-home-screen">
      <View style={styles.brandCopy}>
        <AppText variant="headline">{t('app.name')}</AppText>
        <AppText muted>{t('app.tagline')}</AppText>
      </View>

      <PageHeader
        description={t('connection.home.description')}
        eyebrow={t('connection.home.eyebrow')}
        title={t('connection.home.title')}
      />

      {activeServerUrl === undefined ? null : (
        <SurfaceCard padding="compact" style={styles.activeServer}>
          <View
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            style={[
              styles.iconContainer,
              { backgroundColor: theme.colors.tintMuted },
            ]}
          >
            <AppIcon color={theme.colors.tint} decorative name="server" />
          </View>
          <View style={styles.activeServerCopy}>
            <AppText muted variant="caption">
              {t('connection.home.activeServer')}
            </AppText>
            <AppText selectable variant="headline">
              {activeServerUrl}
            </AppText>
          </View>
        </SurfaceCard>
      )}

      <SurfaceCard
        padding="none"
        style={[
          styles.methodGroup,
          expanded && styles.methodGroupExpanded,
        ]}
      >
        <ConnectionMethodRow
          action={t('connection.home.manualAction')}
          description={t('connection.home.manualDescription')}
          expanded={expanded}
          hint={t('connection.home.manualHint')}
          iconName="link"
          onPress={onEnterAddress}
          testID="connection-method-address"
          title={t('connection.home.manualTitle')}
        />
        <ConnectionMethodRow
          action={t('connection.home.qrAction')}
          description={t('connection.home.qrDescription')}
          expanded={expanded}
          hint={t('connection.home.qrHint')}
          iconName="scan"
          onPress={onScanQr}
          secondary
          testID="connection-method-qr"
          title={t('connection.home.qrTitle')}
        />
      </SurfaceCard>

      {mode === 'signed-out' && onManageProfiles !== undefined ? (
        <AppButton
          accessibilityHint={t('connection.home.manageHint')}
          fullWidth
          label={t('connection.home.manageAction')}
          leadingIcon={
            <AppIcon color={theme.colors.text} decorative name="server" />
          }
          onPress={onManageProfiles}
          testID="manage-server-profiles"
          variant="secondary"
        />
      ) : null}

      <InlineNotice body={t('connection.home.trustNotice')} />
    </ScreenScaffold>
  );
}

type ConnectionMethodRowProps = Readonly<{
  action: string;
  description: string;
  expanded: boolean;
  hint: string;
  iconName: 'link' | 'scan';
  onPress: () => void;
  secondary?: boolean;
  testID: string;
  title: string;
}>;

function ConnectionMethodRow({
  action,
  description,
  expanded,
  hint,
  iconName,
  onPress,
  secondary = false,
  testID,
  title,
}: ConnectionMethodRowProps): ReactNode {
  const theme = useAppTheme();

  return (
    <Pressable
      accessibilityHint={hint}
      accessibilityLabel={action}
      accessibilityRole="button"
      hitSlop={2}
      onPress={onPress}
      style={({ pressed }) => [
        styles.method,
        { borderColor: theme.colors.border },
        secondary &&
          (expanded ? styles.methodDividerExpanded : styles.methodDivider),
        pressed && { backgroundColor: theme.colors.tintMuted },
      ]}
      testID={testID}
    >
      <View
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
        style={[
          styles.iconContainer,
          {
            backgroundColor: secondary
              ? theme.colors.cardStrong
              : theme.colors.tintMuted,
          },
        ]}
      >
        <AppIcon
          color={secondary ? theme.colors.text : theme.colors.tint}
          decorative
          name={iconName}
        />
      </View>
      <View style={styles.methodCopy}>
        <AppText variant="headline">{title}</AppText>
        <AppText muted>{description}</AppText>
        <View style={styles.actionLabel}>
          <AppText style={{ color: theme.colors.tint }} variant="label">
            {action}
          </AppText>
          <AppIcon
            color={theme.colors.tint}
            decorative
            name="chevron-right"
            size={20}
          />
        </View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  actionLabel: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 4,
    marginTop: 4,
  },
  activeServer: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 12,
  },
  activeServerCopy: {
    flex: 1,
    gap: 2,
  },
  brandCopy: {
    gap: 2,
  },
  iconContainer: {
    alignItems: 'center',
    borderRadius: 14,
    height: 48,
    justifyContent: 'center',
    width: 48,
  },
  method: {
    alignItems: 'flex-start',
    flex: 1,
    flexDirection: 'row',
    gap: 16,
    minHeight: 132,
    padding: 20,
  },
  methodCopy: {
    flex: 1,
    gap: 6,
  },
  methodDivider: {
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  methodDividerExpanded: {
    borderLeftWidth: StyleSheet.hairlineWidth,
    borderTopWidth: 0,
  },
  methodGroup: {
    gap: 0,
    overflow: 'hidden',
  } satisfies ViewStyle,
  methodGroupExpanded: {
    flexDirection: 'row',
  },
  screen: {
    gap: 24,
  },
});

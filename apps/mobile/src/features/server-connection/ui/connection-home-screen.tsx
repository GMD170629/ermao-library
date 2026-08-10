import type { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { useI18n } from '../../../shared/i18n/public';
import {
  AppButton,
  AppIcon,
  AppText,
  InlineNotice,
  PageIntro,
  ScreenScaffold,
  SurfaceCard,
  SystemListItem,
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

  return (
    <ScreenScaffold contentStyle={styles.screen} testID="connection-home-screen">
      <View style={styles.brandCopy}>
        <AppText variant="headline">{t('app.name')}</AppText>
        <AppText muted>{t('app.tagline')}</AppText>
      </View>

      <PageIntro
        description={t('connection.home.description')}
        eyebrow={t('connection.home.eyebrow')}
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

      <SurfaceCard padding="none">
        <ConnectionMethodRow
          description={t('connection.home.manualDescription')}
          iconName="link"
          onPress={onEnterAddress}
          testID="connection-method-address"
          title={t('connection.home.manualTitle')}
        />
        <ConnectionMethodRow
          description={t('connection.home.qrDescription')}
          iconName="scan"
          onPress={onScanQr}
          testID="connection-method-qr"
          title={t('connection.home.qrTitle')}
        />
      </SurfaceCard>

      {mode === 'signed-out' && onManageProfiles !== undefined ? (
        <AppButton
          accessibilityHint={t('connection.home.manageHint')}
          fullWidth
          iconName="server"
          label={t('connection.home.manageAction')}
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
  description: string;
  iconName: 'link' | 'scan';
  onPress: () => void;
  testID: string;
  title: string;
}>;

function ConnectionMethodRow({
  description,
  iconName,
  onPress,
  testID,
  title,
}: ConnectionMethodRowProps): ReactNode {
  return (
    <SystemListItem
      iconName={iconName}
      label={title}
      onPress={onPress}
      supportingText={description}
      testID={testID}
    />
  );
}

const styles = StyleSheet.create({
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
  screen: {
    gap: 24,
  },
});

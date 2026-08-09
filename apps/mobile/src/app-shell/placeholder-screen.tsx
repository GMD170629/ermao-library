import type { ReactNode } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { useI18n, type MessageKey } from '../shared/i18n/public';
import {
  AppText,
  AppButton,
  SurfaceCard,
  useAppTheme,
} from '../shared/ui/public';

export type PlaceholderScreenProps = Readonly<{
  action?: Readonly<{
    hintKey: MessageKey;
    labelKey: MessageKey;
    onPress(): void;
  }>;
  descriptionKey: MessageKey;
  detail?: string;
  titleKey: MessageKey;
}>;

export function PlaceholderScreen({
  action,
  descriptionKey,
  detail,
  titleKey,
}: PlaceholderScreenProps): ReactNode {
  const { t } = useI18n();
  const theme = useAppTheme();

  return (
    <ScrollView
      automaticallyAdjustKeyboardInsets
      contentContainerStyle={styles.scrollContent}
      keyboardShouldPersistTaps="handled"
    >
      <View
        accessibilityLabel={t('shell.contentLabel')}
        style={styles.content}
      >
        <View style={styles.heading}>
          <AppText variant="caption">
            {t('shell.placeholder')}
          </AppText>
          <AppText
            accessibilityRole="header"
            variant="title"
          >
            {t(titleKey)}
          </AppText>
          <AppText muted>
            {t(descriptionKey)}
          </AppText>
          {detail === undefined ? null : (
            <AppText selectable>{detail}</AppText>
          )}
        </View>

        <SurfaceCard>
          <View
            style={[
              styles.statusIndicator,
              { backgroundColor: theme.colors.tintMuted },
            ]}
          >
            <View
              accessibilityElementsHidden
              importantForAccessibility="no"
              style={[
                styles.statusDot,
                { backgroundColor: theme.colors.tint },
              ]}
            />
            <AppText variant="headline">
              {t('shell.ready')}
            </AppText>
          </View>
          <AppText muted>
            {t('app.tagline')}
          </AppText>
          {action === undefined ? null : (
            <AppButton
              accessibilityHint={t(action.hintKey)}
              label={t(action.labelKey)}
              onPress={action.onPress}
            />
          )}
        </SurfaceCard>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {
    alignSelf: 'center',
    gap: 28,
    maxWidth: 760,
    width: '100%',
  },
  heading: {
    gap: 10,
  },
  scrollContent: {
    flexGrow: 1,
    padding: 24,
  },
  statusDot: {
    borderRadius: 5,
    height: 10,
    width: 10,
  },
  statusIndicator: {
    alignItems: 'center',
    alignSelf: 'flex-start',
    borderRadius: 16,
    flexDirection: 'row',
    gap: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
});

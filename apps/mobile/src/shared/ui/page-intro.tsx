import type { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { AppText } from './app-text';
import { useAppTheme } from './theme-provider';

export type PageIntroProps = Readonly<{
  description?: string;
  eyebrow?: string;
  title?: string;
  trailing?: ReactNode;
}>;

export function PageIntro({
  description,
  eyebrow,
  title,
  trailing,
}: PageIntroProps): ReactNode {
  const theme = useAppTheme();
  if (description === undefined && eyebrow === undefined && title === undefined) {
    return null;
  }
  return (
    <View style={{ gap: theme.spacing.xs }}>
      {eyebrow === undefined ? null : (
        <AppText muted variant="caption">
          {eyebrow}
        </AppText>
      )}
      {title === undefined ? null : (
        <View style={[styles.titleRow, { gap: theme.spacing.md }]}>
          <AppText
            accessibilityRole="header"
            style={styles.title}
            variant="largeTitle"
          >
            {title}
          </AppText>
          {trailing}
        </View>
      )}
      {description === undefined ? null : (
        <AppText muted>{description}</AppText>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  title: { flex: 1, minWidth: 0 },
  titleRow: { alignItems: 'center', flexDirection: 'row' },
});

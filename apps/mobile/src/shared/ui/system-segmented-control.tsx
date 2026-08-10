import NativeSegmentedControl from '@expo/ui/community/segmented-control';
import type { ReactNode } from 'react';
import { StyleSheet } from 'react-native';

import { notifySelectionChanged } from './system-feedback';
import { useAppTheme } from './theme-provider';

export type SystemSegmentedOption<Value extends string> = Readonly<{
  label: string;
  value: Value;
}>;

export type SystemSegmentedControlProps<Value extends string> = Readonly<{
  disabled?: boolean;
  onChange(value: Value): void;
  options: readonly SystemSegmentedOption<Value>[];
  testID?: string;
  value: Value;
}>;

export function SystemSegmentedControl<Value extends string>({
  disabled = false,
  onChange,
  options,
  testID,
  value,
}: SystemSegmentedControlProps<Value>): ReactNode {
  const theme = useAppTheme();
  const selectedIndex = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  );
  return (
    <NativeSegmentedControl
      appearance={theme.isDark ? 'dark' : 'light'}
      enabled={!disabled}
      onChange={(event) => {
        const selected = options[event.nativeEvent.selectedSegmentIndex];
        if (selected === undefined || selected.value === value) return;
        void notifySelectionChanged();
        onChange(selected.value);
      }}
      selectedIndex={selectedIndex}
      style={styles.control}
      {...(testID === undefined ? {} : { testID })}
      tintColor={theme.colors.tint}
      values={options.map((option) => option.label)}
    />
  );
}

const styles = StyleSheet.create({
  control: { minHeight: 40, minWidth: 176 },
});

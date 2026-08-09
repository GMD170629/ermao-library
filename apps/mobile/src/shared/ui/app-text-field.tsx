import {
  forwardRef,
  useState,
  type ReactNode,
} from 'react';
import {
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type TextStyle,
  type ViewStyle,
} from 'react-native';

import { AppIcon, type AppIconName } from './app-icon';
import { AppText } from './app-text';
import { useAppTheme } from './theme-provider';

type ForwardedTextInputProps = Pick<
  TextInputProps,
  | 'autoCapitalize'
  | 'autoComplete'
  | 'autoCorrect'
  | 'keyboardType'
  | 'maxLength'
  | 'onBlur'
  | 'onFocus'
  | 'onSubmitEditing'
  | 'returnKeyType'
  | 'secureTextEntry'
  | 'textContentType'
>;

export type AppTextFieldProps = Readonly<{
  disabled?: boolean | undefined;
  error?: string | undefined;
  hint?: string | undefined;
  inputStyle?: StyleProp<TextStyle>;
  label: string;
  labelAction?: ReactNode;
  leadingIconName?: AppIconName | undefined;
  onChangeText: (value: string) => void;
  placeholder?: string | undefined;
  style?: StyleProp<ViewStyle>;
  testID?: string;
  trailingAction?: ReactNode;
  value: string;
}> &
  ForwardedTextInputProps;

export const AppTextField = forwardRef<TextInput, AppTextFieldProps>(
  function AppTextField(
    {
      disabled = false,
      error,
      hint,
      inputStyle,
      label,
      labelAction,
      leadingIconName,
      onBlur,
      onChangeText,
      onFocus,
      placeholder,
      style,
      testID,
      trailingAction,
      value,
      ...textInputProps
    },
    ref,
  ): ReactNode {
    const theme = useAppTheme();
    const [focused, setFocused] = useState(false);
    const supportingText = error ?? hint;
    const borderColor =
      error === undefined ? theme.colors.borderStrong : theme.colors.danger;
    const focusColor =
      error === undefined ? theme.colors.focus : theme.colors.danger;

    return (
      <View style={[{ gap: theme.spacing.xs }, style]}>
        <View
          style={{
            alignItems: 'center',
            flexDirection: 'row',
            gap: theme.spacing.sm,
            justifyContent: 'space-between',
          }}
        >
          <AppText style={{ flexShrink: 1 }} variant="label">
            {label}
          </AppText>
          {labelAction}
        </View>
        <View
          style={{
            alignItems: 'center',
            backgroundColor: theme.colors.cardStrong,
            borderColor,
            borderRadius: theme.radius.control,
            borderWidth: 1,
            flexDirection: 'row',
            gap: theme.spacing.sm,
            minHeight: theme.control.regularHeight,
            opacity: disabled ? 0.5 : 1,
            paddingHorizontal: theme.spacing.md,
            position: 'relative',
          }}
          testID={testID === undefined ? undefined : `${testID}-container`}
        >
          {focused ? (
            <View
              accessibilityElementsHidden
              importantForAccessibility="no-hide-descendants"
              pointerEvents="none"
              style={{
                borderColor: focusColor,
                borderRadius: theme.radius.control,
                borderWidth: 3,
                bottom: 0,
                left: 0,
                position: 'absolute',
                right: 0,
                top: 0,
              }}
              testID={
                testID === undefined ? undefined : `${testID}-focus-ring`
              }
            />
          ) : null}
          {leadingIconName === undefined ? null : (
            <AppIcon
              color={
                error === undefined
                  ? theme.colors.textMuted
                  : theme.colors.danger
              }
              name={leadingIconName}
              size={theme.control.iconSmall}
            />
          )}
          <TextInput
            {...textInputProps}
            accessibilityHint={supportingText}
            accessibilityLabel={label}
            accessibilityState={{ disabled }}
            allowFontScaling
            editable={!disabled}
            onBlur={(event) => {
              setFocused(false);
              onBlur?.(event);
            }}
            onChangeText={onChangeText}
            onFocus={(event) => {
              setFocused(true);
              onFocus?.(event);
            }}
            placeholder={placeholder}
            placeholderTextColor={theme.colors.textMuted}
            ref={ref}
            selectionColor={theme.colors.tint}
            style={[
              {
                color: theme.colors.text,
                flex: 1,
                fontSize: theme.type.body.fontSize,
                lineHeight: theme.type.body.lineHeight,
                minHeight: theme.control.regularHeight,
                paddingVertical: theme.spacing.sm,
              },
              inputStyle,
            ]}
            testID={testID}
            value={value}
          />
          {trailingAction === undefined ? null : (
            <View style={{ alignSelf: 'center' }}>{trailingAction}</View>
          )}
        </View>
        {supportingText === undefined ? null : (
          <AppText
            accessibilityLiveRegion={error === undefined ? 'polite' : 'assertive'}
            style={
              error === undefined ? undefined : { color: theme.colors.danger }
            }
            variant="caption"
          >
            {supportingText}
          </AppText>
        )}
      </View>
    );
  },
);

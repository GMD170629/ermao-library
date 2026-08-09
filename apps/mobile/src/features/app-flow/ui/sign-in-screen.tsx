import { useRef, useState, type ReactNode } from 'react';
import {
  Image,
  Platform,
  Pressable,
  StyleSheet,
  View,
  type ImageSourcePropType,
  type TextInput,
} from 'react-native';

import {
  validateSignInCredentials,
  type SignInFieldErrors,
} from '../../identity/public';
import {
  parseServerAddress,
  type ServerAddressErrorCode,
  type ServerProfilePersistenceWarning,
} from '../../server-connection/public';
import { useI18n, type MessageKey } from '../../../shared/i18n/public';
import {
  AppButton,
  AppText,
  AppTextField,
  InlineNotice,
  ScreenScaffold,
  useAppTheme,
} from '../../../shared/ui/public';

const MAXIMUM_SERVER_ADDRESS_LENGTH = 2_048;
const MAXIMUM_EMAIL_LENGTH = 254;
const MAXIMUM_PASSWORD_LENGTH = 128;
const SIGN_IN_CONTENT_MAX_WIDTH = 353;
const BRAND_LOGO_SIZE = 64;

const brandLogoSource: ImageSourcePropType =
  Platform.OS === 'android'
    ? require('../../../../assets/brand/android-legacy-icon.png')
    : require('../../../../assets/brand/ios-app-icon.png');

export type SignInIssue =
  | Readonly<{
      area: 'url';
      reason: ServerAddressErrorCode;
    }>
  | Readonly<{
      area: 'server';
      reason:
        | 'cancelled'
        | 'incompatible'
        | 'incompatible-response'
        | 'network'
        | 'timeout'
        | 'unhealthy'
        | 'unknown';
    }>
  | Readonly<{
      area: 'profile';
      reason:
        | 'capacity'
        | 'conflict'
        | 'corrupt-storage'
        | 'not-found'
        | 'storage-unavailable'
        | 'unknown';
    }>
  | Readonly<{
      area: 'session';
      reason:
        | 'account-disabled'
        | 'cancelled'
        | 'incompatible-response'
        | 'invalid-credentials'
        | 'network'
        | 'setup-required'
        | 'timeout'
        | 'unknown';
    }>;

export type SignInScreenProps = Readonly<{
  initialEmail?: string;
  initialServerAddress?: string;
  issue?: SignInIssue;
  phase: 'authenticating' | 'connecting' | 'idle';
  profileWarnings: readonly ServerProfilePersistenceWarning[];
  setupRequired: boolean;
  onCancel(): void;
  onManageConnections(): void;
  onSignIn(credentials: Readonly<{
    serverAddress: string;
    email: string;
    password: string;
  }>): void;
}>;

const sessionIssueMessageKeys: Readonly<
  Record<Extract<SignInIssue, { area: 'session' }>['reason'], MessageKey>
> = {
  'account-disabled': 'identity.signIn.issue.accountDisabled',
  cancelled: 'identity.signIn.issue.cancelled',
  'incompatible-response': 'identity.signIn.issue.incompatible',
  'invalid-credentials': 'identity.signIn.issue.invalidCredentials',
  network: 'identity.signIn.issue.network',
  'setup-required': 'identity.signIn.issue.setupRequired',
  timeout: 'identity.signIn.issue.timeout',
  unknown: 'identity.signIn.issue.unknown',
};

function credentialErrorMessageKey(
  field: 'email' | 'password',
  error: NonNullable<SignInFieldErrors[typeof field]>,
): MessageKey {
  if (field === 'email') {
    if (error === 'required') return 'identity.signIn.emailRequired';
    if (error === 'too-long') return 'identity.signIn.emailTooLong';
    return 'identity.signIn.emailInvalid';
  }
  return error === 'too-long'
    ? 'identity.signIn.passwordTooLong'
    : 'identity.signIn.passwordRequired';
}

function clearCredentialError(
  errors: SignInFieldErrors,
  field: 'email' | 'password',
): SignInFieldErrors {
  if (field === 'email') {
    return errors.password === undefined
      ? {}
      : { password: errors.password };
  }
  return errors.email === undefined ? {} : { email: errors.email };
}

function profileWarningMessageKey(
  warning: ServerProfilePersistenceWarning,
): MessageKey {
  return warning.kind === 'recovered-older-snapshot'
    ? 'connection.profiles.warningRecoveredOlderSnapshot'
    : 'connection.profiles.warningMaintenanceCleanupFailed';
}

export function SignInScreen({
  initialEmail = '',
  initialServerAddress = '',
  issue,
  phase,
  profileWarnings,
  setupRequired,
  onCancel,
  onManageConnections,
  onSignIn,
}: SignInScreenProps): ReactNode {
  const { locale, t } = useI18n();
  const theme = useAppTheme();
  const serverInput = useRef<TextInput>(null);
  const emailInput = useRef<TextInput>(null);
  const passwordInput = useRef<TextInput>(null);
  const [serverAddress, setServerAddress] = useState(initialServerAddress);
  const [email, setEmail] = useState(initialEmail);
  const [password, setPassword] = useState('');
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [serverAddressIssue, setServerAddressIssue] =
    useState<ServerAddressErrorCode>();
  const [credentialErrors, setCredentialErrors] =
    useState<SignInFieldErrors>({});
  const busy = phase !== 'idle';

  const serverError =
    serverAddressIssue !== undefined ||
    issue?.area === 'url' ||
    issue?.area === 'server'
      ? t('identity.signIn.serverUnavailable')
      : undefined;
  const emailError =
    credentialErrors.email === undefined
      ? undefined
      : t(credentialErrorMessageKey('email', credentialErrors.email));
  const passwordError =
    credentialErrors.password === undefined
      ? issue?.area === 'session' &&
        issue.reason === 'invalid-credentials'
        ? t(sessionIssueMessageKeys[issue.reason])
        : undefined
      : t(
          credentialErrorMessageKey(
            'password',
            credentialErrors.password,
          ),
        );
  const sessionNoticeKey =
    issue?.area === 'session' &&
    issue.reason !== 'invalid-credentials' &&
    !(issue.reason === 'setup-required' && setupRequired)
      ? sessionIssueMessageKeys[issue.reason]
      : undefined;
  const retrying =
    issue !== undefined ||
    serverAddressIssue !== undefined ||
    credentialErrors.email !== undefined ||
    credentialErrors.password !== undefined;

  function submit(): void {
    if (busy) return;
    const parsedServerAddress = parseServerAddress(serverAddress);
    const validatedCredentials = validateSignInCredentials({
      email,
      password,
    });
    setServerAddressIssue(
      parsedServerAddress.ok ? undefined : parsedServerAddress.code,
    );
    setCredentialErrors(
      validatedCredentials.ok ? {} : validatedCredentials.errors,
    );

    if (!parsedServerAddress.ok) {
      serverInput.current?.focus();
      return;
    }
    if (!validatedCredentials.ok) {
      if (validatedCredentials.errors.email !== undefined) {
        emailInput.current?.focus();
      } else {
        passwordInput.current?.focus();
      }
      return;
    }
    const initialParsedServerAddress = parseServerAddress(
      initialServerAddress,
    );
    if (
      setupRequired &&
      (!initialParsedServerAddress.ok ||
        initialParsedServerAddress.baseUrl.value ===
          parsedServerAddress.baseUrl.value)
    ) {
      serverInput.current?.focus();
      return;
    }
    onSignIn({
      serverAddress: parsedServerAddress.baseUrl.value,
      email: validatedCredentials.credentials.email,
      password: validatedCredentials.credentials.password,
    });
  }

  return (
    <ScreenScaffold
      accessibilityLanguage={locale}
      contentStyle={styles.screen}
      testID="sign-in-screen"
    >
      <View
        style={[
          styles.main,
          {
            gap: theme.spacing.xxl,
            maxWidth: SIGN_IN_CONTENT_MAX_WIDTH,
            paddingTop: theme.spacing.xl,
          },
        ]}
      >
        <View style={[styles.brand, { gap: theme.spacing.sm }]}>
          <Image
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            resizeMode="cover"
            source={brandLogoSource}
            style={{
              borderRadius: theme.radius.control,
              height: BRAND_LOGO_SIZE,
              width: BRAND_LOGO_SIZE,
            }}
            testID="sign-in-brand-logo"
          />
          <AppText accessibilityRole="header" variant="headline">
            {t('app.name')}
          </AppText>
        </View>

        <View style={[styles.form, { gap: theme.spacing.md }]}>
          <AppTextField
            autoCapitalize="none"
            autoComplete="url"
            autoCorrect={false}
            disabled={busy}
            error={serverError}
            keyboardType="url"
            label={t('identity.signIn.serverLabel')}
            labelAction={
              <Pressable
                accessibilityHint={t(
                  'identity.signIn.manageConnectionsHint',
                )}
                accessibilityLabel={t(
                  'identity.signIn.manageConnections',
                )}
                accessibilityRole="button"
                accessibilityState={{ disabled: busy }}
                disabled={busy}
                hitSlop={13}
                onPress={onManageConnections}
                style={({ pressed }) => [
                  pressed && styles.pressed,
                  busy && styles.disabled,
                ]}
              >
                <AppText
                  style={{ color: theme.colors.tint }}
                  variant="caption"
                >
                  {t('identity.signIn.manageConnections')}
                </AppText>
              </Pressable>
            }
            maxLength={MAXIMUM_SERVER_ADDRESS_LENGTH}
            onChangeText={(value) => {
              setServerAddress(value);
              setServerAddressIssue(undefined);
            }}
            onSubmitEditing={() => emailInput.current?.focus()}
            placeholder={t('identity.signIn.serverPlaceholder')}
            ref={serverInput}
            returnKeyType="next"
            testID="sign-in-server"
            textContentType="URL"
            value={serverAddress}
          />

          {profileWarnings.map((warning) => (
            <InlineNotice
              body={t(profileWarningMessageKey(warning))}
              key={warning.kind}
              title={t('connection.profiles.warningTitle')}
              tone="warning"
            />
          ))}

          {issue?.area === 'profile' ? (
            <InlineNotice
              body={t('identity.signIn.profileUnavailable')}
              title={t('identity.signIn.issueTitle')}
              tone="danger"
            />
          ) : null}

          {setupRequired ? (
            <InlineNotice
              body={t('identity.signIn.setupRequiredBody')}
              title={t('identity.signIn.setupRequiredTitle')}
              tone="warning"
            />
          ) : null}

          <AppTextField
            autoCapitalize="none"
            autoComplete="email"
            autoCorrect={false}
            disabled={busy}
            error={emailError}
            keyboardType="email-address"
            label={t('identity.signIn.accountLabel')}
            maxLength={MAXIMUM_EMAIL_LENGTH}
            onChangeText={(value) => {
              setEmail(value);
              if (credentialErrors.email !== undefined) {
                setCredentialErrors((current) =>
                  clearCredentialError(current, 'email'),
                );
              }
            }}
            onSubmitEditing={() => passwordInput.current?.focus()}
            placeholder={t('identity.signIn.accountPlaceholder')}
            ref={emailInput}
            returnKeyType="next"
            testID="sign-in-email"
            textContentType="username"
            value={email}
          />

          <AppTextField
            autoCapitalize="none"
            autoComplete="current-password"
            autoCorrect={false}
            disabled={busy}
            error={passwordError}
            label={t('identity.signIn.passwordLabel')}
            maxLength={MAXIMUM_PASSWORD_LENGTH}
            onChangeText={(value) => {
              setPassword(value);
              if (credentialErrors.password !== undefined) {
                setCredentialErrors((current) =>
                  clearCredentialError(current, 'password'),
                );
              }
            }}
            onSubmitEditing={submit}
            placeholder={t('identity.signIn.passwordPlaceholder')}
            ref={passwordInput}
            returnKeyType="done"
            secureTextEntry={!passwordVisible}
            testID="sign-in-password"
            textContentType="password"
            trailingAction={
              <Pressable
                accessibilityLabel={
                  passwordVisible
                    ? t('identity.signIn.hidePassword')
                    : t('identity.signIn.showPassword')
                }
                accessibilityRole="button"
                accessibilityState={{
                  disabled: busy,
                  selected: passwordVisible,
                }}
                disabled={busy}
                hitSlop={4}
                onPress={() =>
                  setPasswordVisible((currentVisible) => !currentVisible)
                }
                style={({ pressed }) => [
                  styles.passwordVisibility,
                  pressed && styles.pressed,
                  busy && styles.disabled,
                ]}
                testID="sign-in-password-visibility"
              >
                <AppText
                  style={{ color: theme.colors.tint }}
                  variant="label"
                >
                  {passwordVisible
                    ? t('identity.signIn.hidePassword')
                    : t('identity.signIn.showPassword')}
                </AppText>
              </Pressable>
            }
            value={password}
          />

          {sessionNoticeKey === undefined ? null : (
            <InlineNotice
              body={t(sessionNoticeKey)}
              title={t('identity.signIn.issueTitle')}
              tone={issue?.reason === 'cancelled' ? 'info' : 'danger'}
            />
          )}

          <AppButton
            accessibilityHint={t('identity.signIn.submitHint')}
            fullWidth
            label={
              phase === 'connecting'
                ? t('identity.signIn.connecting')
                : phase === 'authenticating'
                  ? t('identity.signIn.authenticating')
                : retrying
                  ? t('identity.signIn.retrySubmit')
                  : t('identity.signIn.submit')
            }
            loading={busy}
            onPress={submit}
            testID="submit-sign-in"
          />
        </View>
      </View>

      {busy ? (
        <AppButton
          fullWidth
          label={t('common.cancel')}
          onPress={onCancel}
          style={[
            styles.footer,
            {
              marginTop: theme.spacing.xxl,
              maxWidth: SIGN_IN_CONTENT_MAX_WIDTH,
            },
          ]}
          testID="cancel-sign-in"
          variant="secondary"
        />
      ) : (
        <View
          accessible
          accessibilityLabel={t('identity.signIn.scanStatus')}
          style={[
            styles.scanStatus,
            {
              gap: theme.spacing.xs,
              maxWidth: SIGN_IN_CONTENT_MAX_WIDTH,
              paddingTop: theme.spacing.xxl,
            },
          ]}
        >
          <AppText style={{ color: theme.colors.brand }} variant="label">
            {t('identity.signIn.scan')}
          </AppText>
          <AppText muted variant="caption">
            {t('identity.signIn.scanUnavailable')}
          </AppText>
        </View>
      )}
    </ScreenScaffold>
  );
}

const styles = StyleSheet.create({
  brand: {
    alignItems: 'center',
  },
  disabled: {
    opacity: 0.45,
  },
  form: {
    width: '100%',
  },
  footer: {
    alignSelf: 'center',
    width: '100%',
  },
  main: {
    alignSelf: 'center',
    width: '100%',
  },
  passwordVisibility: {
    alignItems: 'center',
    height: 44,
    justifyContent: 'center',
    minWidth: 44,
  },
  pressed: {
    opacity: 0.65,
  },
  scanStatus: {
    alignItems: 'baseline',
    alignSelf: 'center',
    flexDirection: 'row',
    justifyContent: 'center',
    width: '100%',
  },
  screen: {
    justifyContent: 'space-between',
  },
});

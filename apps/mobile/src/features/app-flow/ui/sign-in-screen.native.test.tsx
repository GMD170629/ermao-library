import type { ReactNode } from 'react';
import { fireEvent, render } from '@testing-library/react-native';

import { I18nProvider } from '../../../shared/i18n/public';
import { AppThemeProvider } from '../../../shared/ui/public';
import {
  SignInScreen,
  type SignInIssue,
  type SignInScreenProps,
} from './sign-in-screen';

let mockLanguageTag = 'en-US';

jest.mock('expo-localization', () => ({
  useLocales: () => [{ languageTag: mockLanguageTag }],
}));

const noOperation = (): void => undefined;

function Fixture({
  initialServerAddress = 'https://library.example.com',
  initialEmail,
  issue,
  onCancel = noOperation,
  onManageConnections = noOperation,
  onSignIn,
  phase = 'idle',
  setupRequired = false,
}: Readonly<{
  initialServerAddress?: string;
  initialEmail?: string;
  issue?: SignInIssue;
  onCancel?: () => void;
  onManageConnections?: () => void;
  onSignIn: SignInScreenProps['onSignIn'];
  phase?: SignInScreenProps['phase'];
  setupRequired?: boolean;
}>): ReactNode {
  return (
    <AppThemeProvider colorScheme="light">
      <I18nProvider>
        <SignInScreen
          {...(initialEmail === undefined ? {} : { initialEmail })}
          initialServerAddress={initialServerAddress}
          {...(issue === undefined ? {} : { issue })}
          onCancel={onCancel}
          onManageConnections={onManageConnections}
          onSignIn={onSignIn}
          phase={phase}
          profileWarnings={[]}
          setupRequired={setupRequired}
        />
      </I18nProvider>
    </AppThemeProvider>
  );
}

describe('SignInScreen', () => {
  beforeEach(() => {
    mockLanguageTag = 'en-US';
  });

  test('renders the Figma hierarchy and submits normalized credentials', async () => {
    const onSignIn = jest.fn();
    const view = await render(
      <Fixture
        initialEmail=" Reader@Example.com "
        initialServerAddress=" https://library.example.com/base/ "
        onSignIn={onSignIn}
      />,
    );

    expect(
      view.getByTestId('sign-in-brand-logo', {
        includeHiddenElements: true,
      }),
    ).toHaveStyle({
      height: 64,
      width: 64,
    });
    expect(view.getByText('Ermao Books')).toBeOnTheScreen();
    expect(view.queryByText('Welcome back')).toBeNull();
    expect(view.queryByText('Read quietly with Ermao')).toBeNull();

    const server = view.getByLabelText('Server');
    const account = view.getByLabelText('Account');
    const password = view.getByLabelText('Password');
    expect(server).toHaveProp('placeholder', 'https://library.example.com');
    expect(server).toHaveProp('maxLength', 2_048);
    expect(account).toHaveProp('placeholder', 'Enter your account');
    expect(account).toHaveProp('maxLength', 254);
    expect(password).toHaveProp('placeholder', 'Enter your password');
    expect(password).toHaveProp('maxLength', 128);
    expect(view.getByText('Scan to sign in')).toBeOnTheScreen();
    expect(view.getByText('Not available yet')).toBeOnTheScreen();

    expect(account).toHaveProp('value', ' Reader@Example.com ');
    await fireEvent.changeText(password, ' password with spaces ');
    await fireEvent.press(view.getByRole('button', { name: 'Sign in' }));

    expect(onSignIn).toHaveBeenCalledWith({
      serverAddress: 'https://library.example.com/base',
      email: 'Reader@Example.com',
      password: ' password with spaces ',
    });
  });

  test('uses Chinese Figma copy without adding a title or tagline', async () => {
    mockLanguageTag = 'zh-CN';
    const view = await render(<Fixture onSignIn={jest.fn()} />);

    expect(view.getByText('二毛图书')).toBeOnTheScreen();
    expect(view.queryByText('欢迎回来')).toBeNull();
    expect(view.queryByText('和二毛一起，安静读书')).toBeNull();
    expect(view.getByLabelText('服务器')).toHaveProp(
      'placeholder',
      'https://library.example.com',
    );
    expect(view.getByLabelText('账号')).toHaveProp(
      'placeholder',
      '请输入账号',
    );
    expect(view.getByLabelText('密码')).toHaveProp(
      'placeholder',
      '请输入密码',
    );
    expect(view.getByText('扫码登录')).toBeOnTheScreen();
    expect(view.getByText('暂未开放')).toBeOnTheScreen();
  });

  test('keeps the first invalid server error beside its field', async () => {
    mockLanguageTag = 'zh-CN';
    const view = await render(
      <Fixture
        initialServerAddress="server://invalid"
        onSignIn={jest.fn()}
      />,
    );
    await fireEvent.changeText(
      view.getByLabelText('账号'),
      'reader@example.com',
    );
    await fireEvent.changeText(view.getByLabelText('密码'), 'password');

    await fireEvent.press(view.getByRole('button', { name: '登录' }));

    expect(
      view.getByText(
        '无法连接到此服务器，请检查地址后重试',
      ),
    ).toHaveProp('accessibilityLiveRegion', 'assertive');
    expect(view.getByRole('button', { name: '重新登录' })).toBeOnTheScreen();
  });

  test('reserves Next for field navigation and submits with Done', async () => {
    const onSignIn = jest.fn();
    const view = await render(<Fixture onSignIn={onSignIn} />);
    const server = view.getByLabelText('Server');
    const account = view.getByLabelText('Account');
    const password = view.getByLabelText('Password');

    await fireEvent(server, 'submitEditing');
    expect(onSignIn).not.toHaveBeenCalled();
    await fireEvent.changeText(account, 'reader@example.com');
    await fireEvent(account, 'submitEditing');
    expect(onSignIn).not.toHaveBeenCalled();
    await fireEvent.changeText(password, 'password');
    await fireEvent(password, 'submitEditing');

    expect(onSignIn).toHaveBeenCalledWith({
      serverAddress: 'https://library.example.com',
      email: 'reader@example.com',
      password: 'password',
    });
  });

  test('toggles password visibility with an explicit native button', async () => {
    const view = await render(<Fixture onSignIn={jest.fn()} />);
    const password = view.getByLabelText('Password');
    const show = view.getByRole('button', { name: 'Show' });

    expect(password).toHaveProp('secureTextEntry', true);
    expect(show).toBeEnabled();
    await fireEvent.press(show);

    expect(password).toHaveProp('secureTextEntry', false);
    expect(view.getByRole('button', { name: 'Hide' })).toBeEnabled();
  });

  test.each([
    ['connecting', 'Connecting…'],
    ['authenticating', 'Signing in…'],
  ] as const)(
    'keeps the primary action loading and moves cancel to the footer while %s',
    async (phase, loadingLabel) => {
      const onCancel = jest.fn();
      const view = await render(
        <Fixture
          onCancel={onCancel}
          onSignIn={jest.fn()}
          phase={phase}
        />,
      );

      expect(
        view.getByRole('button', { name: loadingLabel }),
      ).toBeDisabled();
      expect(view.getByLabelText('Server')).toBeDisabled();
      expect(view.queryByText('Scan to sign in')).toBeNull();
      await fireEvent.press(view.getByRole('button', { name: 'Cancel' }));
      expect(onCancel).toHaveBeenCalledTimes(1);
    },
  );

  test('maps session errors beside credentials and exposes connection management', async () => {
    const onManageConnections = jest.fn();
    const view = await render(
      <Fixture
        issue={{ area: 'session', reason: 'invalid-credentials' }}
        onManageConnections={onManageConnections}
        onSignIn={jest.fn()}
      />,
    );

    expect(
      view.getByText(
        'The email or password is incorrect. Check both and try again.',
      ),
    ).toBeOnTheScreen();
    await fireEvent.press(
      view.getByRole('button', { name: 'Manage connections' }),
    );
    expect(onManageConnections).toHaveBeenCalledTimes(1);
  });

  test('blocks login for the same uninitialized server', async () => {
    const onSignIn = jest.fn();
    const view = await render(
      <Fixture onSignIn={onSignIn} setupRequired />,
    );
    await fireEvent.changeText(
      view.getByLabelText('Account'),
      'reader@example.com',
    );
    await fireEvent.changeText(view.getByLabelText('Password'), 'password');

    await fireEvent.press(view.getByRole('button', { name: 'Sign in' }));

    expect(onSignIn).not.toHaveBeenCalled();
    expect(
      view.getByText('Finish library setup first'),
    ).toBeOnTheScreen();
  });
});

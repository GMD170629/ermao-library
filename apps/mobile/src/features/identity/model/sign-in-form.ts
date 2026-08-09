export type SignInCredentials = Readonly<{
  email: string;
  password: string;
}>;

export type SignInFieldErrors = Readonly<{
  email?: 'invalid' | 'required' | 'too-long';
  password?: 'required' | 'too-long';
}>;

export type SignInValidationResult =
  | Readonly<{
      credentials: SignInCredentials;
      ok: true;
    }>
  | Readonly<{
      errors: SignInFieldErrors;
      ok: false;
    }>;

const MAX_EMAIL_LENGTH = 254;
const MAX_PASSWORD_LENGTH = 128;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/u;

export function validateSignInCredentials(
  input: SignInCredentials,
): SignInValidationResult {
  const email = input.email.trim();
  const errors: {
    email?: 'invalid' | 'required' | 'too-long';
    password?: 'required' | 'too-long';
  } = {};

  if (email.length === 0) {
    errors.email = 'required';
  } else if (email.length > MAX_EMAIL_LENGTH) {
    errors.email = 'too-long';
  } else if (!EMAIL_PATTERN.test(email)) {
    errors.email = 'invalid';
  }

  if (input.password.length === 0) {
    errors.password = 'required';
  } else if (input.password.length > MAX_PASSWORD_LENGTH) {
    errors.password = 'too-long';
  }

  if (errors.email !== undefined || errors.password !== undefined) {
    return { ok: false, errors };
  }
  return {
    ok: true,
    credentials: { email, password: input.password },
  };
}

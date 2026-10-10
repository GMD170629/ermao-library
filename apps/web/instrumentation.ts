export async function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    const { installServerExceptionObserver } = await import('./lib/server-exceptions');
    installServerExceptionObserver();
  }
}

export const onRequestError: import('next').Instrumentation.onRequestError = async (error) => {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    const { recordServerException } = await import('./lib/server-exceptions');
    recordServerException(error);
  }
};

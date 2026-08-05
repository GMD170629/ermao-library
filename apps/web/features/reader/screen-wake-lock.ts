export type ScreenWakeLockSentinel = { release: () => Promise<void> };

export type ScreenWakeLockPort = {
  request: (type: 'screen') => Promise<ScreenWakeLockSentinel>;
};

export function readerWakeLockPort(navigatorValue: Navigator): ScreenWakeLockPort | null {
  const candidate = navigatorValue as Navigator & { wakeLock?: ScreenWakeLockPort };
  return typeof candidate.wakeLock?.request === 'function' ? candidate.wakeLock : null;
}

export function createScreenWakeLockController(documentValue: Document, port: ScreenWakeLockPort) {
  let sentinel: ScreenWakeLockSentinel | null = null;
  let stopped = false;

  const release = async () => {
    const active = sentinel;
    sentinel = null;
    if (active) await active.release().catch(() => undefined);
  };
  const acquire = async () => {
    if (stopped || documentValue.visibilityState !== 'visible' || sentinel) return;
    sentinel = await port.request('screen').catch(() => null);
  };
  const visibilityChanged = () => {
    if (documentValue.visibilityState === 'visible') void acquire();
    else void release();
  };

  return {
    start() {
      stopped = false;
      documentValue.addEventListener('visibilitychange', visibilityChanged);
      void acquire();
    },
    stop() {
      stopped = true;
      documentValue.removeEventListener('visibilitychange', visibilityChanged);
      void release();
    }
  };
}

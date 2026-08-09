import { useMemo, type ReactNode } from 'react';

import { MobileRootProviders } from '../app-shell/public';
import { mobileRuntime } from '../bootstrap/mobile-runtime';
import {
  AppFlowController,
  AppFlowProvider,
  AbortAppFlowCancellationFactory,
  FeatureAppFlowGateway,
  ProtectedApplicationRoutes,
  useAppFlow,
} from '../features/app-flow/public';

function ConnectedApplicationRoutes(): ReactNode {
  const { state } = useAppFlow();
  return <ProtectedApplicationRoutes state={state} />;
}

export default function RootLayout(): ReactNode {
  const controller = useMemo(
    () =>
      new AppFlowController(
        new FeatureAppFlowGateway({
          connectServer: mobileRuntime.connectServer,
          identitySession: mobileRuntime.identitySession,
          loadServerProfiles: mobileRuntime.loadServerProfiles,
          selectServerProfile: mobileRuntime.selectServerProfile,
        }),
        new AbortAppFlowCancellationFactory(),
      ),
    [],
  );

  return (
    <MobileRootProviders>
      <AppFlowProvider controller={controller}>
        <ConnectedApplicationRoutes />
      </AppFlowProvider>
    </MobileRootProviders>
  );
}

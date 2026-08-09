import type { ReactNode } from 'react';

import { mobileRuntime } from '../../bootstrap/mobile-runtime';
import {
  AbortAppFlowCancellationFactory,
  ServerProfilesFlowScreen,
} from '../../features/app-flow/public';

const services = {
  deleteServerProfile: mobileRuntime.deleteServerProfile,
  loadServerProfiles: mobileRuntime.loadServerProfiles,
  resetCorruptServerProfiles: mobileRuntime.resetCorruptServerProfiles,
};
const cancellations = new AbortAppFlowCancellationFactory();

export default function ServerConnectionsRoute(): ReactNode {
  return (
    <ServerProfilesFlowScreen
      cancellations={cancellations}
      services={services}
    />
  );
}

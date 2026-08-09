import type { ReactNode } from 'react';

import {
  ProtectedConnectionRoutes,
  useAppFlow,
} from '../../features/app-flow/public';

export default function ConnectionLayout(): ReactNode {
  const { state } = useAppFlow();
  return <ProtectedConnectionRoutes state={state} />;
}

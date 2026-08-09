import { Redirect } from 'expo-router';
import type { ReactNode } from 'react';

import {
  PlaceholderScreen,
  StandaloneApplicationSurface,
} from '../app-shell/public';
import {
  appFlowAnchorHref,
  useAppFlow,
} from '../features/app-flow/public';

export default function ApplicationAnchor(): ReactNode {
  const flow = useAppFlow();
  const anchorHref = appFlowAnchorHref(flow.state);

  if (anchorHref !== null) return <Redirect href={anchorHref} />;

  const activeServerUrl =
    flow.state.phase === 'verifying-server' ||
    flow.state.phase === 'restoring-session'
      ? flow.state.profile.baseUrl.value
      : undefined;

  return (
    <StandaloneApplicationSurface>
      <PlaceholderScreen
        {...(activeServerUrl === undefined
          ? {}
          : { detail: activeServerUrl })}
        descriptionKey="route.connection.description"
        titleKey="route.connection.title"
      />
    </StandaloneApplicationSurface>
  );
}

import { registerRootComponent } from 'expo';

import './src/bootstrap/mobile-runtime';

function MobileApplicationRoot(): null {
  return null;
}

registerRootComponent(MobileApplicationRoot);

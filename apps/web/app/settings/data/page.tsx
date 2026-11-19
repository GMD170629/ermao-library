import { Suspense } from 'react';
import { DataSystemSettingsPage } from '../../../features/settings/center/data-system-settings-page';

export default function Page() {
  return <Suspense fallback={null}><DataSystemSettingsPage /></Suspense>;
}

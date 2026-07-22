import { Suspense } from 'react';
import { EmailSettingsPage } from '../../../features/settings/center/email-settings-page';

export default function Page() {
  return <Suspense fallback={null}><EmailSettingsPage /></Suspense>;
}

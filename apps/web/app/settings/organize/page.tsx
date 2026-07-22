import { Suspense } from 'react';
import { OrganizeSettingsPage } from '../../../features/settings/center/organize-settings-page';

export default function Page() {
  return <Suspense fallback={null}><OrganizeSettingsPage /></Suspense>;
}

import { Suspense } from 'react';
import { LibraryImportSettingsPage } from '../../../features/settings/center/library-import-settings-page';

export default function Page() {
  return <Suspense fallback={null}><LibraryImportSettingsPage /></Suspense>;
}

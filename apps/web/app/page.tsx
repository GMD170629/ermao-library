import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { DashboardPage } from '../features/dashboard/dashboard-page';

export default function HomePage() {
  if (!cookies().get('shuku_session')?.value) {
    redirect('/login');
  }

  return <DashboardPage />;
}

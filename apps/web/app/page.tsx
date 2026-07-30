import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { DashboardPage } from '../features/dashboard/dashboard-page';

export default async function HomePage() {
  const cookieStore = await cookies();
  if (!cookieStore.get('shuku_session')?.value) {
    redirect('/login');
  }

  return <DashboardPage />;
}

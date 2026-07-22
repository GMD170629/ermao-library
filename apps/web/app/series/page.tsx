import { SeriesPage } from '../../features/series/series-page';

export default function Page({ searchParams }: { searchParams?: { name?: string } }) {
  return <SeriesPage initialName={searchParams?.name ?? ''} />;
}
